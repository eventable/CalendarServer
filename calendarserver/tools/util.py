##
# Copyright (c) 2008-2015 Apple Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##

"""
Utility functionality shared between calendarserver tools.
"""

__all__ = [
    "loadConfig",
    "UsageError",
    "booleanArgument",
]

import datetime
import os
from time import sleep
import socket
from pwd import getpwnam
from grp import getgrnam
from uuid import UUID

from calendarserver.tools import diagnose

from twistedcaldav.config import config, ConfigurationError
from twistedcaldav.stdconfig import DEFAULT_CONFIG_FILE


from twext.python.log import Logger
from twisted.internet.defer import inlineCallbacks, returnValue

from txdav.xml import element as davxml


from twistedcaldav import memcachepool
from txdav.base.propertystore.base import PropertyName
from txdav.xml import element
from pycalendar.datetime import DateTime, Timezone


log = Logger()


def loadConfig(configFileName):
    """
    Helper method for command-line utilities to load configuration plist
    and override certain values.
    """
    if configFileName is None:
        configFileName = DEFAULT_CONFIG_FILE

    if not os.path.isfile(configFileName):
        raise ConfigurationError("No config file: %s" % (configFileName,))

    config.load(configFileName)

    # Command-line utilities always want these enabled:
    config.EnableCalDAV = True
    config.EnableCardDAV = True

    return config



class UsageError (StandardError):
    pass



def booleanArgument(arg):
    if arg in ("true", "yes", "yup", "uh-huh", "1", "t", "y"):
        return True
    elif arg in ("false", "no", "nope", "nuh-uh", "0", "f", "n"):
        return False
    else:
        raise ValueError("Not a boolean: %s" % (arg,))



def autoDisableMemcached(config):
    """
    Set ClientEnabled to False for each pool whose memcached is not running
    """

    for pool in config.Memcached.Pools.itervalues():
        if pool.ClientEnabled:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((pool.BindAddress, pool.Port))
                s.close()

            except socket.error:
                pool.ClientEnabled = False



def setupMemcached(config):
    #
    # Connect to memcached
    #
    memcachepool.installPools(
        config.Memcached.Pools,
        config.Memcached.MaxClients
    )
    autoDisableMemcached(config)



def checkDirectory(dirpath, description, access=None, create=None, wait=False):
    """
    Make sure dirpath is an existing directory, and optionally ensure it has the
    expected permissions.  Alternatively the function can create the directory or
    can wait for someone else to create it.

    @param dirpath: The directory path we're checking
    @type dirpath: string
    @param description: A description of what the directory path represents, used in
        log messages
    @type description: string
    @param access: The type of access we're expecting, either os.W_OK or os.R_OK
    @param create: A tuple of (file permissions mode, username, groupname) to use
        when creating the directory.  If create=None then no attempt will be made
        to create the directory.
    @type create: tuple
    @param wait: Wether the function should wait in a loop for the directory to be
        created by someone else (or mounted, etc.)
    @type wait: boolean
    """

    # Note: we have to use print here because the logging mechanism has not
    # been set up yet.

    if not os.path.exists(dirpath) or (diagnose.detectPhantomVolume(dirpath) == diagnose.EXIT_CODE_PHANTOM_DATA_VOLUME):

        if wait:

            # If we're being told to wait, post an alert that we can't continue
            # until the volume is mounted
            if not os.path.exists(dirpath) or (diagnose.detectPhantomVolume(dirpath) == diagnose.EXIT_CODE_PHANTOM_DATA_VOLUME):
                from calendarserver.tap.util import postAlert
                postAlert("MissingDataVolumeAlert", ["volumePath", dirpath])

            while not os.path.exists(dirpath) or (diagnose.detectPhantomVolume(dirpath) == diagnose.EXIT_CODE_PHANTOM_DATA_VOLUME):
                if not os.path.exists(dirpath):
                    print("Path does not exist: %s" % (dirpath,))
                else:
                    print("Path is not a real volume: %s" % (dirpath,))
                sleep(5)
        else:
            try:
                mode, username, groupname = create
            except TypeError:
                raise ConfigurationError("%s does not exist: %s"
                                         % (description, dirpath))
            try:
                os.mkdir(dirpath)
            except (OSError, IOError), e:
                print("Could not create %s: %s" % (dirpath, e))
                raise ConfigurationError(
                    "%s does not exist and cannot be created: %s"
                    % (description, dirpath)
                )

            if username:
                uid = getpwnam(username).pw_uid
            else:
                uid = -1

            if groupname:
                gid = getgrnam(groupname).gr_gid
            else:
                gid = -1

            try:
                os.chmod(dirpath, mode)
                os.chown(dirpath, uid, gid)
            except (OSError, IOError), e:
                print("Unable to change mode/owner of %s: %s" % (dirpath, e))

            print("Created directory: %s" % (dirpath,))

    if not os.path.isdir(dirpath):
        raise ConfigurationError("%s is not a directory: %s" % (description, dirpath))

    if access and not os.access(dirpath, access):
        raise ConfigurationError(
            "Insufficient permissions for server on %s directory: %s"
            % (description, dirpath)
        )



@inlineCallbacks
def principalForPrincipalID(principalID, checkOnly=False, directory=None):

    # Allow a directory parameter to be passed in, but default to config.directory
    # But config.directory isn't set right away, so only use it when we're doing more
    # than checking.
    if not checkOnly and not directory:
        directory = config.directory

    if principalID.startswith("/"):
        segments = principalID.strip("/").split("/")
        if (
            len(segments) == 3 and
            segments[0] == "principals" and segments[1] == "__uids__"
        ):
            uid = segments[2]
        else:
            raise ValueError("Can't resolve all paths yet")

        if checkOnly:
            returnValue(None)

        returnValue((yield directory.principalCollection.principalForUID(uid)))

    if principalID.startswith("("):
        try:
            i = principalID.index(")")

            if checkOnly:
                returnValue(None)

            recordType = principalID[1:i]
            shortName = principalID[i + 1:]

            if not recordType or not shortName or "(" in recordType:
                raise ValueError()

            returnValue((yield directory.principalCollection.principalForShortName(recordType, shortName)))

        except ValueError:
            pass

    if ":" in principalID:
        if checkOnly:
            returnValue(None)

        recordType, shortName = principalID.split(":", 1)

        returnValue((yield directory.principalCollection.principalForShortName(recordType, shortName)))

    try:
        UUID(principalID)

        if checkOnly:
            returnValue(None)

        returnValue((yield directory.principalCollection.principalForUID(principalID)))
    except ValueError:
        pass

    raise ValueError("Invalid principal identifier: %s" % (principalID,))



@inlineCallbacks
def recordForPrincipalID(directory, principalID, checkOnly=False):

    if principalID.startswith("/"):
        segments = principalID.strip("/").split("/")
        if (
            len(segments) == 3 and
            segments[0] == "principals" and segments[1] == "__uids__"
        ):
            uid = segments[2]
        else:
            raise ValueError("Can't resolve all paths yet")

        if checkOnly:
            returnValue(None)

        returnValue((yield directory.recordWithUID(uid)))

    if principalID.startswith("("):
        try:
            i = principalID.index(")")

            if checkOnly:
                returnValue(None)

            recordType = directory.oldNameToRecordType(principalID[1:i])
            shortName = principalID[i + 1:]

            if not recordType or not shortName or "(" in recordType:
                raise ValueError()

            returnValue((yield directory.recordWithShortName(recordType, shortName)))

        except ValueError:
            pass

    if ":" in principalID:
        if checkOnly:
            returnValue(None)

        recordType, shortName = principalID.split(":", 1)
        recordType = directory.oldNameToRecordType(recordType)
        if recordType is None:
            returnValue(None)

        returnValue((yield directory.recordWithShortName(recordType, shortName)))

    try:
        if checkOnly:
            returnValue(None)

        returnValue((yield directory.recordWithUID(principalID)))
    except ValueError:
        pass

    raise ValueError("Invalid principal identifier: %s" % (principalID,))



def proxySubprincipal(principal, proxyType):
    return principal.getChild("calendar-proxy-" + proxyType)



@inlineCallbacks
def action_addProxyPrincipal(rootResource, directory, store, principal, proxyType, proxyPrincipal):
    try:
        (yield addProxy(rootResource, directory, store, principal, proxyType, proxyPrincipal))
        print("Added %s as a %s proxy for %s" % (
            prettyPrincipal(proxyPrincipal), proxyType,
            prettyPrincipal(principal)))
    except ProxyError, e:
        print("Error:", e)
    except ProxyWarning, e:
        print(e)



@inlineCallbacks
def action_removeProxyPrincipal(rootResource, directory, store, principal, proxyPrincipal, **kwargs):
    try:
        removed = (yield removeProxy(
            rootResource, directory, store,
            principal, proxyPrincipal, **kwargs
        ))
        if removed:
            print("Removed %s as a proxy for %s" % (
                prettyPrincipal(proxyPrincipal),
                prettyPrincipal(principal)))
    except ProxyError, e:
        print("Error:", e)
    except ProxyWarning, e:
        print(e)



@inlineCallbacks
def addProxy(rootResource, directory, store, principal, proxyType, proxyPrincipal):
    proxyURL = proxyPrincipal.url()

    subPrincipal = proxySubprincipal(principal, proxyType)
    if subPrincipal is None:
        raise ProxyError(
            "Unable to edit %s proxies for %s\n" % (
                proxyType,
                prettyPrincipal(principal)
            )
        )

    membersProperty = (yield subPrincipal.readProperty(davxml.GroupMemberSet, None))

    for memberURL in membersProperty.children:
        if str(memberURL) == proxyURL:
            raise ProxyWarning("%s is already a %s proxy for %s" % (
                prettyPrincipal(proxyPrincipal), proxyType,
                prettyPrincipal(principal)))

    else:
        memberURLs = list(membersProperty.children)
        memberURLs.append(davxml.HRef(proxyURL))
        membersProperty = davxml.GroupMemberSet(*memberURLs)
        (yield subPrincipal.writeProperty(membersProperty, None))

    proxyTypes = ["read", "write"]
    proxyTypes.remove(proxyType)

    yield action_removeProxyPrincipal(
        rootResource, directory, store,
        principal, proxyPrincipal, proxyTypes=proxyTypes
    )

    # Schedule work the PeerConnectionPool will pick up as overdue
    def groupPollNow(txn):
        from txdav.who.groups import GroupCacherPollingWork
        return GroupCacherPollingWork.reschedule(txn, 0, force=True)
    yield store.inTransaction("addProxy groupPollNow", groupPollNow)



@inlineCallbacks
def removeProxy(rootResource, directory, store, principal, proxyPrincipal, **kwargs):
    removed = False
    proxyTypes = kwargs.get("proxyTypes", ("read", "write"))
    for proxyType in proxyTypes:
        proxyURL = proxyPrincipal.url()

        subPrincipal = proxySubprincipal(principal, proxyType)
        if subPrincipal is None:
            raise ProxyError(
                "Unable to edit %s proxies for %s\n" % (
                    proxyType,
                    prettyPrincipal(principal)
                )
            )

        membersProperty = (yield subPrincipal.readProperty(davxml.GroupMemberSet, None))

        memberURLs = [
            m for m in membersProperty.children
            if str(m) != proxyURL
        ]

        if len(memberURLs) == len(membersProperty.children):
            # No change
            continue
        else:
            removed = True

        membersProperty = davxml.GroupMemberSet(*memberURLs)
        (yield subPrincipal.writeProperty(membersProperty, None))

    if removed:
        # Schedule work the PeerConnectionPool will pick up as overdue
        def groupPollNow(txn):
            from txdav.who.groups import GroupCacherPollingWork
            return GroupCacherPollingWork.reschedule(txn, 0, force=True)
        yield store.inTransaction("removeProxy groupPollNow", groupPollNow)
    returnValue(removed)



def prettyPrincipal(principal):
    prettyRecord(principal.record)



def prettyRecord(record):
    try:
        shortNames = record.shortNames
    except AttributeError:
        shortNames = []
    return "\"{d}\" {uid} ({rt}) {sn}".format(
        d=record.displayName.encode("utf-8"),
        rt=record.recordType.name,
        uid=record.uid,
        sn=(", ".join([sn.encode("utf-8") for sn in shortNames]))
    )



def displayNameForCollection(collection):
    try:
        displayName = collection.properties()[
            PropertyName.fromElement(element.DisplayName)
        ]
        displayName = displayName.toString()
    except:
        displayName = collection.name()

    return displayName



def agoString(delta):
    if delta.days:
        agoString = "{} days ago".format(delta.days)
    elif delta.seconds:
        if delta.seconds < 60:
            agoString = "{} second{} ago".format(delta.seconds, "s" if delta.seconds > 1 else "")
        else:
            minutesAgo = delta.seconds / 60
            if minutesAgo < 60:
                agoString = "{} minute{} ago".format(minutesAgo, "s" if minutesAgo > 1 else "")
            else:
                hoursAgo = minutesAgo / 60
                agoString = "{} hour{} ago".format(hoursAgo, "s" if hoursAgo > 1 else "")
    return agoString



def locationString(component):
    locationProps = component.properties("LOCATION")
    if locationProps is not None:
        locations = []
        for locationProp in locationProps:
            locations.append(locationProp.value())
        locationString = ", ".join(locations)
    else:
        locationString = ""
    return locationString



@inlineCallbacks
def getEventDetails(event):
    detail = {}

    nowPyDT = DateTime.getNowUTC()
    nowDT = datetime.datetime.utcnow()
    oneYearInFuture = DateTime.getNowUTC()
    oneYearInFuture.offsetDay(365)

    component = yield event.component()
    mainSummary = component.mainComponent().propertyValue("SUMMARY", u"<no title>")
    whenTrashed = event.whenTrashed()
    ago = nowDT - whenTrashed

    detail["summary"] = mainSummary
    detail["whenTrashed"] = agoString(ago)
    detail["recoveryID"] = event._resourceID

    if component.isRecurring():
        detail["recurring"] = True
        detail["instances"] = []
        instances = component.cacheExpandedTimeRanges(oneYearInFuture)
        instances = sorted(instances.instances.values(), key=lambda x: x.start)
        limit = 3
        count = 0
        for instance in instances:
            if instance.start >= nowPyDT:
                summary = instance.component.propertyValue("SUMMARY", u"<no title>")
                location = locationString(instance.component)
                tzid = instance.component.getProperty("DTSTART").parameterValue("TZID", None)
                dtstart = instance.start
                if tzid is not None:
                    timezone = Timezone(tzid=tzid)
                    dtstart.adjustTimezone(timezone)
                detail["instances"].append({
                    "summary": summary,
                    "starttime": dtstart.getLocaleDateTime(DateTime.FULLDATE, False, True, dtstart.getTimezoneID()),
                    "location": location
                })
                count += 1
                limit -= 1
            if limit == 0:
                break

    else:
        detail["recurring"] = False
        dtstart = component.mainComponent().propertyValue("DTSTART")
        detail["starttime"] = dtstart.getLocaleDateTime(DateTime.FULLDATE, False, True, dtstart.getTimezoneID())
        detail["location"] = locationString(component.mainComponent())

    returnValue(detail)



class ProxyError(Exception):
    """
    Raised when proxy assignments cannot be performed
    """



class ProxyWarning(Exception):
    """
    Raised for harmless proxy assignment failures such as trying to add a
    duplicate or remove a non-existent assignment.
    """

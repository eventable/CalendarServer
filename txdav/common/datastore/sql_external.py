# -*- test-case-name: txdav.caldav.datastore.test.test_sql,txdav.carddav.datastore.test.test_sql -*-
##
# Copyright (c) 2013-2015 Apple Inc. All rights reserved.
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
SQL data store.
"""

from twext.python.log import Logger

from twisted.internet.defer import inlineCallbacks, returnValue, succeed

from txdav.base.propertystore.sql import PropertyStore
from txdav.common.datastore.sql import CommonHome, CommonHomeChild, \
    CommonObjectResource
from txdav.common.datastore.sql_notification import NotificationCollection, \
    NotificationObjectRecord
from txdav.common.datastore.sql_tables import _HOME_STATUS_EXTERNAL
from txdav.common.icommondatastore import NonExistentExternalShare, \
    ExternalShareFailed


log = Logger()

class CommonHomeExternal(CommonHome):
    """
    A CommonHome for a user not hosted on this system, but on another pod. This is needed to provide a
    "reference" to the external user so we can share with them. Actual operations to list child resources, etc
    are all stubbed out since no data for the user is actually hosted in this store.
    """

    @classmethod
    def makeSyntheticExternalHome(cls, transaction, diruid, resourceID):
        """
        During migration we need to refer to the remote home as an external home but without have a local representation
        of it in the store. There will be a new local store home for the migrating user that will operate on local store
        objects. The synthetic home operates only on remote objects.

        @param diruid: directory UID of user
        @type diruid: L{str}
        @param resourceID: resource ID in the remote store
        @type resourceID: L{int}
        """
        attrMap = {
            "_resourceID": resourceID,
            "_ownerUID": diruid,
            "_status": _HOME_STATUS_EXTERNAL,
        }
        homeData = [attrMap.get(attr) for attr in cls.homeAttributes()]
        result = cls(transaction, homeData)
        result._childClass = result._childClass._externalClass
        return result


    def __init__(self, transaction, homeData):
        super(CommonHomeExternal, self).__init__(transaction, homeData)


    def initFromStore(self):
        """
        NoOp for an external share as there is no metadata or properties.
        """
        return succeed(self)


    @inlineCallbacks
    def readMetaData(self):
        """
        Read the home metadata from remote home and save as attributes on this object.
        """
        mapping = yield self._txn.store().conduit.send_home_metadata(self)
        self.deserialize(mapping)


    def setStatus(self, newStatus):
        return self._txn.store().conduit.send_home_set_status(self, newStatus)


    def setLocalStatus(self, newStatus):
        """
        Set the status on the object in the local store not the remote one.

        @param newStatus: the new status to set
        @type newStatus: L{int}
        """
        return super(CommonHomeExternal, self).setStatus(newStatus)


    def external(self):
        """
        Is this an external home.

        @return: a string.
        """
        return True


    def objectWithShareUID(self, shareUID):
        """
        No children.
        """
        raise AssertionError("CommonHomeExternal: not supported")


    def invitedObjectWithShareUID(self, shareUID):
        """
        No children.
        """
        raise AssertionError("CommonHomeExternal: not supported")


    @inlineCallbacks
    def createChildWithName(self, name, bindUID=None):
        """
        No real children - only external ones.
        """
        if bindUID is None:
            raise AssertionError("CommonHomeExternal: not supported")
        child = yield super(CommonHomeExternal, self).createChildWithName(name, bindUID)
        returnValue(child)


    def removeChildWithName(self, name, useTrash=True):
        """
        No children.
        """
        raise AssertionError("CommonHomeExternal: not supported")


    @inlineCallbacks
    def removeExternalChild(self, child):
        """
        Remove an external child. Check that it is invalid or unused before calling this because if there
        are valid references to it, removing will break things.
        """
        if child._bindUID is None:
            raise AssertionError("CommonHomeExternal: not supported")
        yield super(CommonHomeExternal, self).removeChildWithName(child.name(), useTrash=False)


    def syncToken(self):
        """
        No children.
        """
        raise AssertionError("CommonHomeExternal: not supported")


    def resourceNamesSinceRevision(self, revision, depth):
        """
        No children.
        """
        raise AssertionError("CommonHomeExternal: not supported")


    @inlineCallbacks
    def _loadPropertyStore(self):
        """
        No property store - stub to a NonePropertyStore.
        """
        props = yield PropertyStore.load(
            self.uid(),
            self.uid(),
            None,
            self._txn,
            self._resourceID,
            notifyCallback=self.notifyChanged
        )
        self._propertyStore = props


    def properties(self):
        return self._propertyStore


    def objectResourcesWithUID(self, uid, ignore_children=[], allowShared=True):
        """
        No children.
        """
        raise AssertionError("CommonHomeExternal: not supported")


    def objectResourceWithID(self, rid):
        """
        No children.
        """
        raise AssertionError("CommonHomeExternal: not supported")


    def notifyChanged(self):
        """
        Notifications are not handled for external homes - make this a no-op.
        """
        return succeed(None)


    def bumpModified(self):
        """
        No changes recorded for external homes - make this a no-op.
        """
        return succeed(None)


    def removeUnacceptedShares(self):
        """
        No children.
        """
        raise AssertionError("CommonHomeExternal: not supported")


    @inlineCallbacks
    def sharedToBindRecords(self):
        results = yield self._txn.store().conduit.send_home_shared_to_records(self)
        returnValue(dict([(
            k,
            (
                self._childClass._bindRecordClass.deserialize(v[0]),
                self._childClass._bindRecordClass.deserialize(v[1]),
                self._childClass._metadataRecordClass.deserialize(v[2]),
            ),
        ) for k, v in results.items()]))



class CommonHomeChildExternal(CommonHomeChild):
    """
    A CommonHomeChild for a collection not hosted on this system, but on another pod. This will forward
    specific apis to the other pod using cross-pod requests.
    """

    @classmethod
    def listObjects(cls, home):
        """
        Retrieve the names of the children that exist in the given home.

        @return: an iterable of C{str}s.
        """

        return home._txn.store().conduit.send_homechild_listobjects(home)


    @classmethod
    @inlineCallbacks
    def loadAllObjects(cls, home):
        raw_results = yield home._txn.store().conduit.send_homechild_loadallobjects(home)

        results = []
        for mapping in raw_results:
            child = yield cls.deserialize(home, mapping)
            results.append(child)
        returnValue(results)


    @classmethod
    @inlineCallbacks
    def objectWith(cls, home, name=None, resourceID=None, bindUID=None, accepted=True, onlyInTrash=False):
        mapping = yield home._txn.store().conduit.send_homechild_objectwith(home, name, resourceID, bindUID, accepted, onlyInTrash)

        if mapping:
            child = yield cls.deserialize(home, mapping)
            returnValue(child)
        else:
            returnValue(None)


    def external(self):
        """
        Is this an external home.

        @return: a string.
        """
        return True


    def fixNonExistentExternalShare(self):
        """
        An external request has returned and indicates the external share no longer exists. That
        means this shared resource is an "orphan" and needs to be remove (uninvited) to clean things up.
        """
        log.error("Non-existent share detected and removed for {share}", share=self)
        ownerView = yield self.ownerView()
        yield ownerView.removeShare(self)


    @inlineCallbacks
    def remove(self):
        """
        External shares are never removed directly - instead they must be "uninvited". However,
        the owner's external calendar can be removed.
        """
        if self.owned():
            yield super(CommonHomeChildExternal, self).remove()
        else:
            raise AssertionError("CommonHomeChildExternal: not supported")


    @inlineCallbacks
    def moveObjectResource(self, child, newparent, newname=None):
        """
        The base class does an optimization to avoid removing/re-creating
        the actual object resource data. That might not always be possible
        with external shares if the shared resource is moved to a collection
        that is not shared or shared by someone else on a different (third)
        pod. The best bet here is to treat the move as a delete/create.
        """
        raise NotImplementedError("TODO: external resource")


    @inlineCallbacks
    def moveObjectResourceHere(self, name, component):
        """
        Create a new child in this collection as part of a move operation. This needs to be split out because
        behavior differs for sub-classes and cross-pod operations.

        @param name: new name to use in new parent
        @type name: C{str} or C{None} for existing name
        @param component: data for new resource
        @type component: L{Component}
        """

        try:
            result = yield self._txn.store().conduit.send_homechild_movehere(self, name, str(component))
        except NonExistentExternalShare:
            yield self.fixNonExistentExternalShare()
            raise ExternalShareFailed("External share does not exist")
        returnValue(result)


    @inlineCallbacks
    def moveObjectResourceAway(self, rid, child=None):
        """
        Remove the child as the result of a move operation. This needs to be split out because
        behavior differs for sub-classes and cross-pod operations.

        @param rid: the child resource-id to move
        @type rid: C{int}
        @param child: the child resource to move - might be C{None} for cross-pod
        @type child: L{CommonObjectResource}
        """

        try:
            result = yield self._txn.store().conduit.send_homechild_moveaway(self, rid)
        except NonExistentExternalShare:
            yield self.fixNonExistentExternalShare()
            raise ExternalShareFailed("External share does not exist")
        returnValue(result)


    @inlineCallbacks
    def syncTokenRevision(self):
        if self._syncTokenRevision is None:
            try:
                revision = yield self._txn.store().conduit.send_homechild_synctokenrevision(self)
            except NonExistentExternalShare:
                yield self.fixNonExistentExternalShare()
                raise ExternalShareFailed("External share does not exist")
        returnValue(revision)


    @inlineCallbacks
    def resourceNamesSinceRevision(self, revision):
        try:
            names = yield self._txn.store().conduit.send_homechild_resourcenamessincerevision(self, revision)
        except NonExistentExternalShare:
            yield self.fixNonExistentExternalShare()
            raise ExternalShareFailed("External share does not exist")

        returnValue(names)


    @inlineCallbacks
    def search(self, filter, **kwargs):
        try:
            results = yield self._txn.store().conduit.send_homechild_search(self, filter.serialize(), **kwargs)
        except NonExistentExternalShare:
            yield self.fixNonExistentExternalShare()
            raise ExternalShareFailed("External share does not exist")

        returnValue(results)


    @inlineCallbacks
    def sharingBindRecords(self):
        results = yield self._txn.store().conduit.send_homechild_sharing_records(self)
        returnValue(dict([(k, self._bindRecordClass.deserialize(v),) for k, v in results.items()]))


    def migrateBindRecords(self, bindUID):
        return self._txn.store().conduit.send_homechild_migrate_sharing_records(self, bindUID)



class CommonObjectResourceExternal(CommonObjectResource):
    """
    A CommonObjectResource for a resource not hosted on this system, but on another pod. This will forward
    specific apis to the other pod using cross-pod requests.
    """

    @classmethod
    @inlineCallbacks
    def loadAllObjects(cls, parent):
        mapping_list = yield parent._txn.store().conduit.send_objectresource_loadallobjects(parent)

        results = []
        if mapping_list:
            for mapping in mapping_list:
                child = yield cls.deserialize(parent, mapping)
                results.append(child)
        returnValue(results)


    @classmethod
    @inlineCallbacks
    def loadAllObjectsWithNames(cls, parent, names):
        mapping_list = yield parent._txn.store().conduit.send_objectresource_loadallobjectswithnames(parent, names)

        results = []
        if mapping_list:
            for mapping in mapping_list:
                child = yield cls.deserialize(parent, mapping)
                results.append(child)
        returnValue(results)


    @classmethod
    def listObjects(cls, parent):
        return parent._txn.store().conduit.send_objectresource_listobjects(parent)


    @classmethod
    def countObjects(cls, parent):
        return parent._txn.store().conduit.send_objectresource_countobjects(parent)


    @classmethod
    @inlineCallbacks
    def objectWith(cls, parent, name=None, uid=None, resourceID=None):
        mapping = yield parent._txn.store().conduit.send_objectresource_objectwith(parent, name, uid, resourceID)

        if mapping:
            child = yield cls.deserialize(parent, mapping)
            returnValue(child)
        else:
            returnValue(None)


    @classmethod
    def resourceNameForUID(cls, parent, uid):
        return parent._txn.store().conduit.send_objectresource_resourcenameforuid(parent, uid)


    @classmethod
    def resourceUIDForName(cls, parent, name):
        return parent._txn.store().conduit.send_objectresource_resourceuidforname(parent, name)


    @classmethod
    @inlineCallbacks
    def create(cls, parent, name, component, options=None):
        mapping = yield parent._txn.store().conduit.send_objectresource_create(parent, name, str(component), options=options)

        if mapping:
            child = yield cls.deserialize(parent, mapping)
            returnValue(child)
        else:
            returnValue(None)


    @inlineCallbacks
    def setComponent(self, component, **kwargs):
        self._componentChanged = yield self._txn.store().conduit.send_objectresource_setcomponent(self, str(component), **kwargs)
        self._cachedComponent = None
        returnValue(self._componentChanged)


    @inlineCallbacks
    def component(self):
        if self._cachedComponent is None:
            text = yield self._txn.store().conduit.send_objectresource_component(self)
            self._cachedComponent = self._componentClass.fromString(text)

        returnValue(self._cachedComponent)


    def remove(self):
        return self._txn.store().conduit.send_objectresource_remove(self)



class NotificationCollectionExternal(NotificationCollection):
    """
    A NotificationCollection for a resource not hosted on this system, but on another pod. This will forward
    specific apis to the other pod using cross-pod requests.
    """

    @classmethod
    def notificationsWithUID(cls, txn, uid, create=False):
        return super(NotificationCollectionExternal, cls).notificationsWithUID(txn, uid, status=_HOME_STATUS_EXTERNAL, create=create)


    def initFromStore(self):
        """
        NoOp for an external share as there are no properties.
        """
        return succeed(self)


    @inlineCallbacks
    def notificationObjectRecords(self):
        results = yield self._txn.store().conduit.send_notification_all_records(self)
        returnValue(map(NotificationObjectRecord.deserialize, results))


    def setStatus(self, newStatus):
        return self._txn.store().conduit.send_notification_set_status(self, newStatus)


    def setLocalStatus(self, newStatus):
        """
        Set the status on the object in the local store not the remote one.

        @param newStatus: the new status to set
        @type newStatus: L{int}
        """
        return super(NotificationCollectionExternal, self).setStatus(newStatus)

NotificationCollection._externalClass = NotificationCollectionExternal

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

from twisted.internet.defer import inlineCallbacks

from txdav.common.datastore.podding.base import FailedCrossPodRequestError


class SharingInvitesConduitMixin(object):
    """
    Defines the cross-pod API for sharing invites that will be mixed into the
    L{PoddingConduit} class.
    """

    @inlineCallbacks
    def send_shareinvite(
        self, txn, homeType, ownerUID, ownerName, shareeUID, shareUID,
        bindMode, bindUID, summary, copy_properties, supported_components
    ):
        """
        Send a sharing invite cross-pod message.

        @param homeType: Type of home being shared.
        @type homeType: C{int}

        @param ownerUID: UID of the sharer.
        @type ownerUID: C{str}

        @param ownerName: owner's name of the sharer calendar
        @type ownerName: C{str}

        @param shareeUID: UID of the sharee
        @type shareeUID: C{str}

        @param shareUID: Resource/invite ID for sharee
        @type shareUID: C{str}

        @param bindMode: bind mode for the share
        @type bindMode: C{str}
        @param bindUID: bind UID of the sharer calendar
        @type bindUID: C{str}
        @param summary: sharing message
        @type summary: C{str}

        @param copy_properties: C{str} name/value for properties to be copied
        @type copy_properties: C{dict}

        @param supported_components: supproted components, may be C{None}
        @type supported_components: C{str}
        """

        _ignore_sender, recipient = yield self.validRequest(
            ownerUID, shareeUID
        )

        request = {
            "action": "shareinvite",
            "type": homeType,
            "owner": ownerUID,
            "owner_name": ownerName,
            "sharee": shareeUID,
            "share_id": shareUID,
            "mode": bindMode,
            "bind_uid": bindUID,
            "summary": summary,
            "properties": copy_properties,
        }
        if supported_components is not None:
            request["supported-components"] = supported_components

        yield self.sendRequest(txn, recipient, request)


    @inlineCallbacks
    def recv_shareinvite(self, txn, request):
        """
        Process a sharing invite cross-pod request.
        Request arguments as per L{send_shareinvite}.

        @param request: request arguments
        @type request: C{dict}
        """

        # Sharee home on this pod must exist (create if needed)
        shareeHome = yield txn.homeWithUID(
            request["type"], request["sharee"], create=True
        )
        if shareeHome is None or shareeHome.external():
            raise FailedCrossPodRequestError("Invalid sharee UID specified")

        # Create a share
        yield shareeHome.processExternalInvite(
            request["owner"],
            request["owner_name"],
            request["share_id"],
            request["mode"],
            request["bind_uid"],
            request["summary"],
            dict([(k, v.encode("utf-8")) for k, v in request["properties"].items()]),
            supported_components=request.get("supported-components")
        )


    @inlineCallbacks
    def send_shareuninvite(
        self, txn, homeType, ownerUID,
        bindUID, shareeUID, shareUID
    ):
        """
        Send a sharing uninvite cross-pod message.

        @param homeType: Type of home being shared.
        @type homeType: C{int}

        @param ownerUID: UID of the sharer.
        @type ownerUID: C{str}
        @param bindUID: bind UID of the sharer calendar
        @type bindUID: C{str}

        @param shareeUID: UID of the sharee
        @type shareeUID: C{str}

        @param shareUID: Resource/invite ID for sharee
        @type shareUID: C{str}
        """

        _ignore_sender, recipient = yield self.validRequest(
            ownerUID, shareeUID
        )

        request = {
            "action": "shareuninvite",
            "type": homeType,
            "owner": ownerUID,
            "bind_uid": bindUID,
            "sharee": shareeUID,
            "share_id": shareUID,
        }

        yield self.sendRequest(txn, recipient, request)


    @inlineCallbacks
    def recv_shareuninvite(self, txn, request):
        """
        Process a sharing uninvite cross-pod request.
        Request arguments as per L{send_shareuninvite}.

        @param request: request arguments
        @type request: C{dict}
        """

        # Sharee home on this pod must already exist
        shareeHome = yield txn.homeWithUID(request["type"], request["sharee"])
        if shareeHome is None or shareeHome.external():
            FailedCrossPodRequestError("Invalid sharee UID specified")

        # Remove a share
        yield shareeHome.processExternalUninvite(
            request["owner"],
            request["bind_uid"],
            request["share_id"],
        )


    @inlineCallbacks
    def send_sharereply(
        self, txn, homeType, ownerUID,
        shareeUID, shareUID, bindStatus, summary=None
    ):
        """
        Send a sharing reply cross-pod message.

        @param homeType: Type of home being shared.
        @type homeType: C{int}
        @param ownerUID: UID of the sharer.
        @type ownerUID: C{str}
        @param shareeUID: UID of the recipient
        @type shareeUID: C{str}
        @param shareUID: Resource/invite ID for recipient
        @type shareUID: C{str}
        @param bindStatus: bind mode for the share
        @type bindStatus: C{str}
        @param summary: sharing message
        @type summary: C{str}
        """

        _ignore_sender, recipient = yield self.validRequest(
            shareeUID, ownerUID
        )

        request = {
            "action": "sharereply",
            "type": homeType,
            "owner": ownerUID,
            "sharee": shareeUID,
            "share_id": shareUID,
            "status": bindStatus,
        }
        if summary is not None:
            request["summary"] = summary

        yield self.sendRequest(txn, recipient, request)


    @inlineCallbacks
    def recv_sharereply(self, txn, request):
        """
        Process a sharing reply cross-pod request.
        Request arguments as per L{send_sharereply}.

        @param request: request arguments
        @type request: C{dict}
        """

        # Sharer home on this pod must already exist
        ownerHome = yield txn.homeWithUID(request["type"], request["owner"])
        if ownerHome is None or ownerHome.external():
            FailedCrossPodRequestError("Invalid owner UID specified")

        # Process a reply
        yield ownerHome.processExternalReply(
            request["owner"],
            request["sharee"],
            request["share_id"],
            request["status"],
            summary=request.get("summary")
        )

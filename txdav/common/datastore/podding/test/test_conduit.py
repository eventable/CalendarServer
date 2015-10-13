##
# Copyright (c) 2005-2015 Apple Inc. All rights reserved.
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

from pycalendar.datetime import DateTime
from pycalendar.period import Period

from twext.python.clsprop import classproperty

import txweb2.dav.test.util
from txweb2.http_headers import MimeType
from txweb2.stream import MemoryStream

from twisted.internet.defer import inlineCallbacks, succeed, returnValue

from twistedcaldav import caldavxml
from twistedcaldav.ical import Component, normalize_iCalStr

from txdav.caldav.datastore.query.filter import Filter
from txdav.caldav.datastore.scheduling.cuaddress import calendarUserFromCalendarUserAddress
from txdav.caldav.datastore.scheduling.freebusy import FreebusyQuery
from txdav.caldav.datastore.scheduling.ischedule.localservers import ServersDB, Server
from txdav.caldav.datastore.sql import ManagedAttachment, AttachmentLink
from txdav.caldav.datastore.test.common import CaptureProtocol
from txdav.common.datastore.podding.conduit import PoddingConduit, \
    FailedCrossPodRequestError
from txdav.common.datastore.podding.resource import ConduitResource
from txdav.common.datastore.podding.test.util import MultiStoreConduitTest, \
    FakeConduitRequest
from txdav.common.datastore.sql_tables import _BIND_STATUS_ACCEPTED
from txdav.common.datastore.test.util import populateCalendarsFrom, CommonCommonTests
from txdav.common.icommondatastore import ObjectResourceNameAlreadyExistsError, \
    ObjectResourceNameNotAllowedError
from txdav.common.idirectoryservice import DirectoryRecordNotFoundError


class TestConduit (CommonCommonTests, txweb2.dav.test.util.TestCase):

    class FakeConduit(object):

        def recv_fake(self, j):
            return succeed({
                "back2u": j["echo"],
                "more": "bits",
            })


    @inlineCallbacks
    def setUp(self):
        yield super(TestConduit, self).setUp()

        serversDB = ServersDB()
        serversDB.addServer(Server("A", "http://127.0.0.1", "A", True))
        serversDB.addServer(Server("B", "http://127.0.0.2", "B", False))

        yield self.buildStoreAndDirectory(serversDB=serversDB)

        self.site.resource.putChild("conduit", ConduitResource(self.site.resource, self.storeUnderTest()))

        yield self.populate()


    @inlineCallbacks
    def populate(self):
        yield populateCalendarsFrom(self.requirements, self.storeUnderTest())
        self.notifierFactory.reset()


    @classproperty(cache=False)
    def requirements(cls): #@NoSelf
        return {
            "user01": {
                "calendar_1": {
                },
                "inbox": {
                },
            },
            "user02": {
                "calendar_1": {
                },
                "inbox": {
                },
            },
            "user03": {
                "calendar_1": {
                },
                "inbox": {
                },
            },
        }


    @inlineCallbacks
    def test_validRequest(self):
        """
        Cross-pod request fails when there is no shared secret header present.
        """

        conduit = PoddingConduit(self.storeUnderTest())
        r1, r2 = yield conduit.validRequest("user01", "puser02")
        self.assertTrue(r1 is not None)
        self.assertTrue(r2 is not None)

        yield self.assertFailure(
            conduit.validRequest("bogus01", "user02"),
            DirectoryRecordNotFoundError
        )

        yield self.assertFailure(
            conduit.validRequest("user01", "bogus02"),
            DirectoryRecordNotFoundError
        )

        yield self.assertFailure(
            conduit.validRequest("user01", "user02"),
            FailedCrossPodRequestError
        )



class TestConduitToConduit(MultiStoreConduitTest):

    class FakeConduit(PoddingConduit):

        @inlineCallbacks
        def send_fake(self, txn, ownerUID, shareeUID):
            _ignore_owner, sharee = yield self.validRequest(ownerUID, shareeUID)
            action = {
                "action": "fake",
                "echo": "bravo"
            }

            result = yield self.sendRequest(txn, sharee, action)
            returnValue(result)


        def recv_fake(self, txn, j):
            return succeed({
                "back2u": j["echo"],
                "more": "bits",
            })


    def makeConduit(self, store):
        """
        Use our own variant.
        """
        conduit = self.FakeConduit(store)
        conduit.conduitRequestClass = FakeConduitRequest
        return conduit


    @inlineCallbacks
    def test_fake_action(self):
        """
        Cross-pod request works when conduit does support the action.
        """

        store = self.theStoreUnderTest(0)
        response = yield store.conduit.send_fake(self.theTransactionUnderTest(0), "user01", "puser01")
        self.assertEqual(response, {"back2u": "bravo", "more": "bits"})
        yield self.commitTransaction(0)

        store = self.theStoreUnderTest(1)
        response = yield store.conduit.send_fake(self.theTransactionUnderTest(1), "puser01", "user01")
        self.assertEqual(response, {"back2u": "bravo", "more": "bits"})
        yield self.commitTransaction(1)



class TestConduitAPI(MultiStoreConduitTest):
    """
    Test that the conduit api works.
    """

    nowYear = {"now": DateTime.getToday().getYear()}

    caldata1 = """BEGIN:VCALENDAR
VERSION:2.0
CALSCALE:GREGORIAN
PRODID:-//CALENDARSERVER.ORG//NONSGML Version 1//EN
BEGIN:VEVENT
UID:uid1
DTSTART:{now:04d}0102T140000Z
DURATION:PT1H
CREATED:20060102T190000Z
DTSTAMP:20051222T210507Z
RRULE:FREQ=WEEKLY
SUMMARY:instance
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").format(**nowYear)

    caldata1_changed = """BEGIN:VCALENDAR
VERSION:2.0
CALSCALE:GREGORIAN
PRODID:-//CALENDARSERVER.ORG//NONSGML Version 1//EN
BEGIN:VEVENT
UID:uid1
DTSTART:{now:04d}0102T150000Z
DURATION:PT1H
CREATED:20060102T190000Z
DTSTAMP:20051222T210507Z
RRULE:FREQ=WEEKLY
SUMMARY:instance changed
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").format(**nowYear)

    caldata2 = """BEGIN:VCALENDAR
VERSION:2.0
CALSCALE:GREGORIAN
PRODID:-//CALENDARSERVER.ORG//NONSGML Version 1//EN
BEGIN:VEVENT
UID:uid2
DTSTART:{now:04d}0102T160000Z
DURATION:PT1H
CREATED:20060102T190000Z
DTSTAMP:20051222T210507Z
RRULE:FREQ=WEEKLY
SUMMARY:instance
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").format(**nowYear)

    caldata3 = """BEGIN:VCALENDAR
VERSION:2.0
CALSCALE:GREGORIAN
PRODID:-//CALENDARSERVER.ORG//NONSGML Version 1//EN
BEGIN:VEVENT
UID:uid3
DTSTART:{now:04d}0102T160000Z
DURATION:PT1H
CREATED:20060102T190000Z
DTSTAMP:20051222T210507Z
RRULE:FREQ=WEEKLY
SUMMARY:instance
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").format(**nowYear)

    @inlineCallbacks
    def test_basic_share(self):
        """
        Test that basic invite/uninvite works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        shared = yield calendar1.shareeView("puser01")
        self.assertEqual(shared.shareStatus(), _BIND_STATUS_ACCEPTED)
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        self.assertTrue(shared is not None)
        self.assertTrue(shared.external())
        yield self.commitTransaction(1)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.uninviteUIDFromShare("puser01")
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        self.assertTrue(shared is None)
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_countobjects(self):
        """
        Test that action=countobjects works.
        """

        yield self.createShare("user01", "puser01")

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        count = yield shared.countObjectResources()
        self.assertEqual(count, 0)
        yield self.commitTransaction(1)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        count = yield calendar1.countObjectResources()
        self.assertEqual(count, 1)
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        count = yield shared.countObjectResources()
        self.assertEqual(count, 1)
        yield self.commitTransaction(1)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        yield object1.remove()
        count = yield calendar1.countObjectResources()
        self.assertEqual(count, 0)
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        count = yield shared.countObjectResources()
        self.assertEqual(count, 0)
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_listobjects(self):
        """
        Test that action=listobjects works.
        """

        yield self.createShare("user01", "puser01")

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        objects = yield shared.listObjectResources()
        self.assertEqual(set(objects), set())
        yield self.commitTransaction(1)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield calendar1.createCalendarObjectWithName("2.ics", Component.fromString(self.caldata2))
        objects = yield calendar1.listObjectResources()
        self.assertEqual(set(objects), set(("1.ics", "2.ics",)))
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        objects = yield shared.listObjectResources()
        self.assertEqual(set(objects), set(("1.ics", "2.ics",)))
        yield self.commitTransaction(1)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        yield object1.remove()
        objects = yield calendar1.listObjectResources()
        self.assertEqual(set(objects), set(("2.ics",)))
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        objects = yield shared.listObjectResources()
        self.assertEqual(set(objects), set(("2.ics",)))
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_synctoken(self):
        """
        Test that action=synctoken works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        token1_1 = yield calendar1.syncTokenRevision()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        token2_1 = yield shared.syncTokenRevision()
        yield self.commitTransaction(1)

        self.assertEqual(token1_1, token2_1)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        token1_2 = yield calendar1.syncTokenRevision()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        token2_2 = yield shared.syncTokenRevision()
        yield self.commitTransaction(1)

        self.assertNotEqual(token1_1, token1_2)
        self.assertEqual(token1_2, token2_2)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        yield object1.remove()
        count = yield calendar1.countObjectResources()
        self.assertEqual(count, 0)
        yield self.commitTransaction(0)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        token1_3 = yield calendar1.syncTokenRevision()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        token2_3 = yield shared.syncTokenRevision()
        yield self.commitTransaction(1)

        self.assertNotEqual(token1_1, token1_3)
        self.assertNotEqual(token1_2, token1_3)
        self.assertEqual(token1_3, token2_3)


    @inlineCallbacks
    def test_resourcenamessincerevision(self):
        """
        Test that action=synctoken works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        token1_1 = yield calendar1.syncToken()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        token2_1 = yield shared.syncToken()
        yield self.commitTransaction(1)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        token1_2 = yield calendar1.syncToken()
        names1 = yield calendar1.resourceNamesSinceToken(token1_1)
        self.assertEqual(names1, ([u"1.ics"], [], [],))
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        token2_2 = yield shared.syncToken()
        names2 = yield shared.resourceNamesSinceToken(token2_1)
        self.assertEqual(names2, ([u"1.ics"], [], [],))
        yield self.commitTransaction(1)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        yield object1.remove()
        count = yield calendar1.countObjectResources()
        self.assertEqual(count, 0)
        yield self.commitTransaction(0)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        token1_3 = yield calendar1.syncToken()
        names1 = yield calendar1.resourceNamesSinceToken(token1_2)
        self.assertEqual(names1, ([], [u"1.ics"], [],))
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        token2_3 = yield shared.syncToken()
        names2 = yield shared.resourceNamesSinceToken(token2_2)
        self.assertEqual(names2, ([], [u"1.ics"], [],))
        yield self.commitTransaction(1)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        names1 = yield calendar1.resourceNamesSinceToken(token1_3)
        self.assertEqual(names1, ([], [], [],))
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        names2 = yield shared.resourceNamesSinceToken(token2_3)
        self.assertEqual(names2, ([], [], [],))
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_resourceuidforname(self):
        """
        Test that action=resourceuidforname works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        uid = yield calendar1.resourceUIDForName("1.ics")
        self.assertEqual(uid, "uid1")
        uid = yield calendar1.resourceUIDForName("2.ics")
        self.assertTrue(uid is None)
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        uid = yield shared.resourceUIDForName("1.ics")
        self.assertEqual(uid, "uid1")
        uid = yield shared.resourceUIDForName("2.ics")
        self.assertTrue(uid is None)
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_resourcenameforuid(self):
        """
        Test that action=resourcenameforuid works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        name = yield calendar1.resourceNameForUID("uid1")
        self.assertEqual(name, "1.ics")
        name = yield calendar1.resourceNameForUID("uid2")
        self.assertTrue(name is None)
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        name = yield shared.resourceNameForUID("uid1")
        self.assertEqual(name, "1.ics")
        name = yield shared.resourceNameForUID("uid2")
        self.assertTrue(name is None)
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_search(self):
        """
        Test that action=resourcenameforuid works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        filter = caldavxml.Filter(
            caldavxml.ComponentFilter(
                *[caldavxml.ComponentFilter(
                    **{"name": ("VEVENT", "VFREEBUSY", "VAVAILABILITY")}
                )],
                **{"name": "VCALENDAR"}
            )
        )
        filter = Filter(filter)

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        names = [item[0] for item in (yield calendar1.search(filter))]
        self.assertEqual(names, ["1.ics", ])
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        names = [item[0] for item in (yield shared.search(filter))]
        self.assertEqual(names, ["1.ics", ])
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_loadallobjects(self):
        """
        Test that action=loadallobjects works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        resource1 = yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        resource_id1 = resource1.id()
        resource2 = yield calendar1.createCalendarObjectWithName("2.ics", Component.fromString(self.caldata2))
        resource_id2 = resource2.id()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resources = yield shared.objectResources()
        byname = dict([(obj.name(), obj) for obj in resources])
        byuid = dict([(obj.uid(), obj) for obj in resources])
        self.assertEqual(len(resources), 2)
        self.assertEqual(set([obj.name() for obj in resources]), set(("1.ics", "2.ics",)))
        self.assertEqual(set([obj.uid() for obj in resources]), set(("uid1", "uid2",)))
        self.assertEqual(set([obj.id() for obj in resources]), set((resource_id1, resource_id2,)))
        resource = yield shared.objectResourceWithName("1.ics")
        self.assertTrue(resource is byname["1.ics"])
        resource = yield shared.objectResourceWithName("2.ics")
        self.assertTrue(resource is byname["2.ics"])
        resource = yield shared.objectResourceWithName("Missing.ics")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithUID("uid1")
        self.assertTrue(resource is byuid["uid1"])
        resource = yield shared.objectResourceWithUID("uid2")
        self.assertTrue(resource is byuid["uid2"])
        resource = yield shared.objectResourceWithUID("uid-missing")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithID(resource_id1)
        self.assertTrue(resource is byname["1.ics"])
        resource = yield shared.objectResourceWithID(resource_id2)
        self.assertTrue(resource is byname["2.ics"])
        resource = yield shared.objectResourceWithID(0)
        self.assertTrue(resource is None)
        yield self.commitTransaction(1)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        yield object1.remove()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resources = yield shared.objectResources()
        byname = dict([(obj.name(), obj) for obj in resources])
        byuid = dict([(obj.uid(), obj) for obj in resources])
        self.assertEqual(len(resources), 1)
        self.assertEqual(set([obj.name() for obj in resources]), set(("2.ics",)))
        self.assertEqual(set([obj.uid() for obj in resources]), set(("uid2",)))
        self.assertEqual(set([obj.id() for obj in resources]), set((resource_id2,)))
        resource = yield shared.objectResourceWithName("1.ics")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithName("2.ics")
        self.assertTrue(resource is byname["2.ics"])
        resource = yield shared.objectResourceWithName("Missing.ics")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithUID("uid1")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithUID("uid2")
        self.assertTrue(resource is byuid["uid2"])
        resource = yield shared.objectResourceWithUID("uid-missing")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithID(resource_id1)
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithID(resource_id2)
        self.assertTrue(resource is byname["2.ics"])
        resource = yield shared.objectResourceWithID(0)
        self.assertTrue(resource is None)
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_loadallobjectswithnames(self):
        """
        Test that action=loadallobjectswithnames works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        resource1 = yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        resource_id1 = resource1.id()
        yield calendar1.createCalendarObjectWithName("2.ics", Component.fromString(self.caldata2))
        resource3 = yield calendar1.createCalendarObjectWithName("3.ics", Component.fromString(self.caldata3))
        resource_id3 = resource3.id()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resources = yield shared.objectResources()
        self.assertEqual(len(resources), 3)
        yield self.commitTransaction(1)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resources = yield shared.objectResourcesWithNames(("1.ics", "3.ics",))
        byname = dict([(obj.name(), obj) for obj in resources])
        byuid = dict([(obj.uid(), obj) for obj in resources])
        self.assertEqual(len(resources), 2)
        self.assertEqual(set([obj.name() for obj in resources]), set(("1.ics", "3.ics",)))
        self.assertEqual(set([obj.uid() for obj in resources]), set(("uid1", "uid3",)))
        self.assertEqual(set([obj.id() for obj in resources]), set((resource_id1, resource_id3,)))
        resource = yield shared.objectResourceWithName("1.ics")
        self.assertTrue(resource is byname["1.ics"])
        resource = yield shared.objectResourceWithName("3.ics")
        self.assertTrue(resource is byname["3.ics"])
        resource = yield shared.objectResourceWithName("Missing.ics")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithUID("uid1")
        self.assertTrue(resource is byuid["uid1"])
        resource = yield shared.objectResourceWithUID("uid3")
        self.assertTrue(resource is byuid["uid3"])
        resource = yield shared.objectResourceWithUID("uid-missing")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithID(resource_id1)
        self.assertTrue(resource is byname["1.ics"])
        resource = yield shared.objectResourceWithID(resource_id3)
        self.assertTrue(resource is byname["3.ics"])
        resource = yield shared.objectResourceWithID(0)
        self.assertTrue(resource is None)
        yield self.commitTransaction(1)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        yield object1.remove()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resources = yield shared.objectResourcesWithNames(("1.ics", "3.ics",))
        byname = dict([(obj.name(), obj) for obj in resources])
        byuid = dict([(obj.uid(), obj) for obj in resources])
        self.assertEqual(len(resources), 1)
        self.assertEqual(set([obj.name() for obj in resources]), set(("3.ics",)))
        self.assertEqual(set([obj.uid() for obj in resources]), set(("uid3",)))
        self.assertEqual(set([obj.id() for obj in resources]), set((resource_id3,)))
        resource = yield shared.objectResourceWithName("1.ics")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithName("3.ics")
        self.assertTrue(resource is byname["3.ics"])
        resource = yield shared.objectResourceWithName("Missing.ics")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithUID("uid1")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithUID("uid3")
        self.assertTrue(resource is byuid["uid3"])
        resource = yield shared.objectResourceWithUID("uid-missing")
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithID(resource_id1)
        self.assertTrue(resource is None)
        resource = yield shared.objectResourceWithID(resource_id3)
        self.assertTrue(resource is byname["3.ics"])
        resource = yield shared.objectResourceWithID(0)
        self.assertTrue(resource is None)
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_objectwith(self):
        """
        Test that action=objectwith works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        resource = yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        resource_id = resource.id()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resource = yield shared.objectResourceWithName("1.ics")
        self.assertTrue(resource is not None)
        self.assertEqual(resource.name(), "1.ics")
        self.assertEqual(resource.uid(), "uid1")

        resource = yield shared.objectResourceWithName("2.ics")
        self.assertTrue(resource is None)

        yield self.commitTransaction(1)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resource = yield shared.objectResourceWithUID("uid1")
        self.assertTrue(resource is not None)
        self.assertEqual(resource.name(), "1.ics")
        self.assertEqual(resource.uid(), "uid1")

        resource = yield shared.objectResourceWithUID("uid2")
        self.assertTrue(resource is None)

        yield self.commitTransaction(1)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resource = yield shared.objectResourceWithID(resource_id)
        self.assertTrue(resource is not None)
        self.assertEqual(resource.name(), "1.ics")
        self.assertEqual(resource.uid(), "uid1")

        resource = yield shared.objectResourceWithID(0)
        self.assertTrue(resource is None)

        yield self.commitTransaction(1)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        yield object1.remove()
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resource = yield shared.objectResourceWithName("1.ics")
        self.assertTrue(resource is None)
        yield self.commitTransaction(1)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resource = yield shared.objectResourceWithUID("uid1")
        self.assertTrue(resource is None)
        yield self.commitTransaction(1)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resource = yield shared.objectResourceWithID(resource_id)
        self.assertTrue(resource is None)
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_create(self):
        """
        Test that action=create works.
        """

        yield self.createShare("user01", "puser01")

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resource = yield shared.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        resource_id = resource.id()
        self.assertTrue(resource is not None)
        self.assertEqual(resource.name(), "1.ics")
        self.assertEqual(resource.uid(), "uid1")
        self.assertFalse(resource._componentChanged)
        yield self.commitTransaction(1)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        resource = yield shared.objectResourceWithUID("uid1")
        self.assertTrue(resource is not None)
        self.assertEqual(resource.name(), "1.ics")
        self.assertEqual(resource.uid(), "uid1")
        self.assertEqual(resource.id(), resource_id)
        yield self.commitTransaction(1)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        self.assertTrue(object1 is not None)
        self.assertEqual(object1.name(), "1.ics")
        self.assertEqual(object1.uid(), "uid1")
        self.assertEqual(object1.id(), resource_id)
        yield self.commitTransaction(0)


    @inlineCallbacks
    def test_create_exception(self):
        """
        Test that action=create fails when a duplicate name is used.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        yield self.failUnlessFailure(shared.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1)), ObjectResourceNameAlreadyExistsError)
        yield self.abortTransaction(1)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")
        yield self.failUnlessFailure(shared.createCalendarObjectWithName(".2.ics", Component.fromString(self.caldata2)), ObjectResourceNameNotAllowedError)
        yield self.abortTransaction(1)


    @inlineCallbacks
    def test_setcomponent(self):
        """
        Test that action=setcomponent works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        ical = yield shared_object.component()
        self.assertTrue(isinstance(ical, Component))
        self.assertEqual(normalize_iCalStr(str(ical)), normalize_iCalStr(self.caldata1))
        yield self.commitTransaction(1)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        changed = yield shared_object.setComponent(Component.fromString(self.caldata1_changed))
        self.assertFalse(changed)
        ical = yield shared_object.component()
        self.assertTrue(isinstance(ical, Component))
        self.assertEqual(normalize_iCalStr(str(ical)), normalize_iCalStr(self.caldata1_changed))
        yield self.commitTransaction(1)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        ical = yield object1.component()
        self.assertTrue(isinstance(ical, Component))
        self.assertEqual(normalize_iCalStr(str(ical)), normalize_iCalStr(self.caldata1_changed))
        yield self.commitTransaction(0)


    @inlineCallbacks
    def test_component(self):
        """
        Test that action=component works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        ical = yield shared_object.component()
        self.assertTrue(isinstance(ical, Component))
        self.assertEqual(normalize_iCalStr(str(ical)), normalize_iCalStr(self.caldata1))
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_remove(self):
        """
        Test that action=remove works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        yield shared_object.remove()
        yield self.commitTransaction(1)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        self.assertTrue(shared_object is None)
        yield self.commitTransaction(1)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        self.assertTrue(object1 is None)
        yield self.commitTransaction(0)


    @inlineCallbacks
    def test_freebusy(self):
        """
        Test that action=component works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        fbstart = "{now:04d}0102T000000Z".format(**self.nowYear)
        fbend = "{now:04d}0103T000000Z".format(**self.nowYear)

        shared = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", name="shared-calendar")

        fbinfo = FreebusyQuery.FBInfo([], [], [])
        timerange = Period(DateTime.parseText(fbstart), DateTime.parseText(fbend))
        organizer = recipient = (yield calendarUserFromCalendarUserAddress("mailto:puser01@example.com", self.theTransactionUnderTest(1)))

        freebusy = FreebusyQuery(organizer=organizer, recipient=recipient, timerange=timerange)
        matchtotal = (yield freebusy.generateFreeBusyInfo([shared, ], fbinfo))

        self.assertEqual(matchtotal, 1)
        self.assertEqual(fbinfo[0], [Period.parseText("{now:04d}0102T140000Z/PT1H".format(**self.nowYear)), ])
        self.assertEqual(len(fbinfo[1]), 0)
        self.assertEqual(len(fbinfo[2]), 0)
        yield self.commitTransaction(1)


    def attachmentToString(self, attachment):
        """
        Convenience to convert an L{IAttachment} to a string.

        @param attachment: an L{IAttachment} provider to convert into a string.

        @return: a L{Deferred} that fires with the contents of the attachment.

        @rtype: L{Deferred} firing C{bytes}
        """
        capture = CaptureProtocol()
        attachment.retrieve(capture)
        return capture.deferred


    @inlineCallbacks
    def test_add_attachment(self):
        """
        Test that action=add-attachment works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        object1 = yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        resourceID = object1.id()
        yield self.commitTransaction(0)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        data = "Here is some text."
        attachment, location = yield shared_object.addAttachment(None, MimeType.fromString("text/plain"), "test.txt", MemoryStream(data))
        managedID = attachment.managedID()
        from txdav.caldav.datastore.sql_external import ManagedAttachmentExternal
        self.assertTrue(isinstance(attachment, ManagedAttachmentExternal))
        self.assertEqual(attachment.size(), len(data))
        self.assertTrue("user01/dropbox/" in location)
        yield self.commitTransaction(1)

        cobjs = yield ManagedAttachment.referencesTo(self.theTransactionUnderTest(0), managedID)
        self.assertEqual(cobjs, set((resourceID,)))
        attachment = yield ManagedAttachment.load(self.theTransactionUnderTest(0), resourceID, managedID)
        self.assertEqual(attachment.name(), "test.txt")
        data = yield self.attachmentToString(attachment)
        self.assertEqual(data, "Here is some text.")
        yield self.commitTransaction(0)


    @inlineCallbacks
    def test_update_attachment(self):
        """
        Test that action=update-attachment works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        resourceID = object1.id()
        attachment, _ignore_location = yield object1.addAttachment(None, MimeType.fromString("text/plain"), "test.txt", MemoryStream("Here is some text."))
        managedID = attachment.managedID()
        yield self.commitTransaction(0)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        data = "Here is some more text."
        attachment, location = yield shared_object.updateAttachment(managedID, MimeType.fromString("text/plain"), "test.txt", MemoryStream(data))
        managedID = attachment.managedID()
        from txdav.caldav.datastore.sql_external import ManagedAttachmentExternal
        self.assertTrue(isinstance(attachment, ManagedAttachmentExternal))
        self.assertEqual(attachment.size(), len(data))
        self.assertTrue("user01/dropbox/" in location)
        yield self.commitTransaction(1)

        cobjs = yield ManagedAttachment.referencesTo(self.theTransactionUnderTest(0), managedID)
        self.assertEqual(cobjs, set((resourceID,)))
        attachment = yield ManagedAttachment.load(self.transactionUnderTest(), resourceID, managedID)
        self.assertEqual(attachment.name(), "test.txt")
        data = yield self.attachmentToString(attachment)
        self.assertEqual(data, "Here is some more text.")
        yield self.commitTransaction(0)


    @inlineCallbacks
    def test_remove_attachment(self):
        """
        Test that action=remove-attachment works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        resourceID = object1.id()
        attachment, _ignore_location = yield object1.addAttachment(None, MimeType.fromString("text/plain"), "test.txt", MemoryStream("Here is some text."))
        managedID = attachment.managedID()
        yield self.commitTransaction(0)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        yield shared_object.removeAttachment(None, managedID)
        yield self.commitTransaction(1)

        cobjs = yield ManagedAttachment.referencesTo(self.theTransactionUnderTest(0), managedID)
        self.assertEqual(cobjs, set())
        attachment = yield ManagedAttachment.load(self.theTransactionUnderTest(0), resourceID, managedID)
        self.assertTrue(attachment is None)
        yield self.commitTransaction(0)


    @inlineCallbacks
    def test_get_all_attachments(self):
        """
        Test that action=get-all-attachments works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        yield object1.addAttachment(None, MimeType.fromString("text/plain"), "test.txt", MemoryStream("Here is some text."))
        yield self.commitTransaction(0)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        attachments = yield shared_object.ownerHome().getAllAttachments()
        self.assertEqual(len(attachments), 1)
        self.assertTrue(isinstance(attachments[0], ManagedAttachment))
        self.assertEqual(attachments[0].contentType(), MimeType.fromString("text/plain"))
        self.assertEqual(attachments[0].name(), "test.txt")
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_get_attachment_data(self):
        """
        Test that action=get-all-attachments works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        yield self.commitTransaction(0)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        attachment, _ignore_location = yield object1.addAttachment(None, MimeType.fromString("text/plain"), "test.txt", MemoryStream("Here is some text."))
        remote_id = attachment.id()
        yield self.commitTransaction(0)

        home1 = yield self.homeUnderTest(txn=self.theTransactionUnderTest(1), name="puser01")
        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        attachment = yield ManagedAttachment._create(self.theTransactionUnderTest(1), None, home1.id())
        attachment._contentType = MimeType.fromString("text/plain")
        attachment._name = "test.txt"
        yield shared_object.ownerHome().readAttachmentData(remote_id, attachment)
        yield self.commitTransaction(1)


    @inlineCallbacks
    def test_get_attachment_links(self):
        """
        Test that action=get-attachment-links works.
        """

        yield self.createShare("user01", "puser01")

        calendar1 = yield self.calendarUnderTest(txn=self.theTransactionUnderTest(0), home="user01", name="calendar")
        cobj1 = yield calendar1.createCalendarObjectWithName("1.ics", Component.fromString(self.caldata1))
        calobjID = cobj1.id()
        yield self.commitTransaction(0)

        object1 = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(0), home="user01", calendar_name="calendar", name="1.ics")
        attachment, _ignore_location = yield object1.addAttachment(None, MimeType.fromString("text/plain"), "test.txt", MemoryStream("Here is some text."))
        attID = attachment.id()
        managedID = attachment.managedID()
        yield self.commitTransaction(0)

        shared_object = yield self.calendarObjectUnderTest(txn=self.theTransactionUnderTest(1), home="puser01", calendar_name="shared-calendar", name="1.ics")
        links = yield shared_object.ownerHome().getAttachmentLinks()
        self.assertEqual(len(links), 1)
        self.assertTrue(isinstance(links[0], AttachmentLink))
        self.assertEqual(links[0]._attachmentID, attID)
        self.assertEqual(links[0]._managedID, managedID)
        self.assertEqual(links[0]._calendarObjectID, calobjID)
        yield self.commitTransaction(1)

----
-- Copyright (c) 2012-2015 Apple Inc. All rights reserved.
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
-- http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.
----

---------------------------------------------------
-- Upgrade database schema from VERSION 44 to 45 --
---------------------------------------------------

-------------------
-- Data Versions --
-------------------

alter table CALENDAR_OBJECT
  add column DATAVERSION integer default 0 not null;

alter table ADDRESSBOOK_OBJECT
  add column DATAVERSION integer default 0 not null;

-- update the version
update CALENDARSERVER set VALUE = '45' where NAME = 'VERSION';

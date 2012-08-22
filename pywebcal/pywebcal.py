# Copyright 2010  Red Hat, Inc.
# Stanislav Ochotnicky <sochotnicky@redhat.com>
#
# This file is part of pywebcal.
#
# pywebcal is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pywebcal is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pywebcal.  If not, see <http://www.gnu.org/licenses/>.

import sys
import StringIO
import datetime
import logging
import pickle
import hashlib
import urllib2
from os import path, environ

try:
    from dateutil.tz import tzical, gettz
    from dateutil.rrule import rrulestr
except ImportError:
    print """You miss dependencies for running this library. Please
install dateutil module (python-dateutil)."""
    sys.exit(1)

try:
    import vobject
except ImportError:
    print """You miss dependencies for running this library. Please
install vobject module (python-vobject). You can find sources of
vobject on http://vobject.skyhouseconsulting.com/. Or install it with
`easy_install vobject`"""
    sys.exit(1)


class WebCal(object):
    """
    Class providing simple cached access to iCal calendars over Http

    """
    _cache_file = '%s/.pywebcal.cache' % environ['HOME']

    def __init__(self, URL, username = None, password = None):
        """URL - URL of webcal calendar. For example
                    http://www.google.com/calendar/ical/9e11j73ff4pdomjlort7v10h640okf47%40import.calendar.google.com/public/basic.ics
        username - provide username in case it is needed
        password - password to access calendar
        """
        self._URL = URL
        self._username = username
        self._password = password
        self.connection = None
        self._modifiedTime = None
        self._cache = None
        self._connID = ConnID(URL, username)
        self._cache_file = "%s.%s" % (self._cache_file, self._connID.digest)

    def get_calendar(self):
        """get_calendar() -> ICal

        Returns Calendar instance from URL
        """
        if not self.connection:
            self._connect()
            self._modifiedTime = datetime.datetime.now(gettz())
        
        modified = self._modifiedTime
        cc = self.__get_cached_calendar()
        
        if cc and cc['modified'] > modified + datetime.timedelta(hours=12): # cache is only valid for 12 hours
            data = cc['data']
            vcal = vobject.base.readComponents(StringIO.StringIO(data[0])).next()
            c = ICal(vcal)
        else:
            vcal = vcal = vobject.base.readComponents(self.connection.read()).next()  ## read from http url
            c = ICal(vcal)
            self.__set_cached_calendar(modified, (vcal.serialize(),))
        return c

    def get_all_events(self):
        """get_all_events() -> [Event, Event1,...]

        Returns all events in all calendars for this connection"""
        if not self.connection:
            self._connect()
        events = []
        
        cal = self.get_calendar()
        events.extend(cal.get_events())
        return events

    def _connect(self):
       
        self.connection = urllib2.urlopen(self._URL)
        # TODO: add auth
        #if self._username and self._password:
        #    self.connection.connection.addBasicAuthorization(self._username, self._password)

    def __set_cached_calendar(self, modified, data):
        if not self._cache:
            self.__load_cache()

        if self._cache and self._cache['modified'] > modified + datetime.timedelta(hours=12):
            return

        self._cache['modified'] = modified
	self._cache['data'] = data
        self.__save_cache()

    def __get_cached_calendar(self):
        if not self._cache:
            self.__load_cache()

        if self._cache:
            return self._cache
        else:
            return None

    def __load_cache(self):
        if not path.isfile(self._cache_file) or path.getsize(self._cache_file) == 0:
            self._cache = {}
            return

        with open(self._cache_file, 'r') as cacheFile:
            self._cache = pickle.load(cacheFile)

    def __save_cache(self):
        with open(self._cache_file, 'w') as cacheFile:
            pickle.dump(self._cache, cacheFile)


class ICal(object):
    """High-level interface for working with iCal files"""

    def __init__(self, vobj):
        """Initializes class with given vobject.icalendar.VCalendar2_0
        instance
        """
        self.ical = vobj

    def get_event_ids(self):
        """get_event_ids() -> [uid, uid1, ...]

        Returns UIDs of all VEVENTs defined in iCal instance. These
        UIDs are used for access to concrete events defined within
        iCal file"""
        uids = []
        try:
            for event in self.ical.vevent_list:
                uids.append(event.uid.value)
        except AttributeError, e:
            # this means ical has no events, maybe just todos?
            # one way or the other -> ignore and return empty list
            pass
        return uids

    def get_events(self):
        """get_events() -> [Event, Event1, ...]

        Returns Event classes defined in iCal instance.
        """
        ret = []
        try:
            for event in self.ical.vevent_list:
                ret.append(Event(self.ical, event))
        except AttributeError, e:
            # this means ical has no events, maybe just todos?
            # one way or the other -> ignore and return empty list
            pass
        return ret

    def events_before(self, dt):
        """events_before(datetime) -> [(datetime, Event), (datetime1, Event1), ...]

        Returns list of tuples of (datetime.datetime, Event)
        where datetime represents date of nearest occurrence (start) of given
        event before dt datetime object
        """
        ret = []
        es = self.get_events()
        # prepare timeless date in case it's needed
        d = dt.date()
        for e in es:
            rule = e.get_rrule()
            if not rule:
                sdate = e.get_start_datetime()
                if type(sdate) == datetime.date:
                    cmpdate = d
                else:
                    cmpdate = dt
                if cmpdate >= sdate:
                    ret.append((sdate, e))
            else:
                d = rule.before(dt, inc=True)
                if d:
                    ret.append((d, e))
        return ret

    def events_between(self, dtstart, dtend):
        """events_before(datetime) -> [(datetime, Event), (datetime1, Event1), ...]

        Returns list of tuples of (datetime.datetime, Event UID)
        where datetime represents date of occurrence (start) of given
        event between dtstart and dtend datetime objects
        """
        ret = []
        es = self.get_events()
        # prepare timeless starts-stops
        dstart, dend = dtstart.date(), dtend.date()
        for e in es:
            rule = e.get_rrule()
            if not rule:
                sdate = e.get_start_datetime()
                if type(sdate) == datetime.date:
                    cmpstart, cmpend = dstart, dend
                else:
                    cmpstart, cmpend = dtstart, dtend

                if cmpstart <= sdate <= cmpend:
                    ret.append((sdate, e))
            else:
                d = rule.between(dtstart, dtend, inc=True)
                if d:
                    ret.append((d, e))
        return ret

    def events_after(self, dt):
        """events_after(datetime) -> [(datetime, Event), (datetime1, Event1), ...]

        Returns list of tuples of (datetime.datetime, Event UID)
        where datetime represents date of nearest occurrence (start) of given
        event after dt datetime object
        """
        ret = []
        es = self.get_events()
        # prepare timeless date in case it's needed
        d = dt.date()
        for e in es:
            rule = e.get_rrule()
            if not rule:
                sdate = e.get_start_datetime()
                if type(sdate) == datetime.date:
                    cmpdate = d
                else:
                    cmpdate = dt
                if cmpdate <= sdate:
                    ret.append((sdate, e))
            else:
                d = rule.after(dt, inc=True)
                if d:
                    ret.append((d, e))
        return ret

    def get_timezones(self):
        """get_timezones() -> [TZID, TZID1, ...]

        Returns list of all TZIDS defined in iCal file or empty list
        if no TZIDs have been defined (all times are in UTC). TZID is for
        example 'Europe/Berlin'
        """
        tzids = []
        for tz in self.ical.walk('VTIMEZONE'):
            tzids.append(tz['TZID'])
        return tzids

class Event(object):
    def __init__(self, ical, event):
        """__init__(ical, vevent) -> Event

        ical - iCal text for the event
        event - vevent instance representing given event
        """
        self.uid = event.uid.value
        self.ical = ical
        self._event = event

    def get_summary(self):
        """get_summary() -> str

        Returns string representing summary of event
        """
        return self._event.summary.value

    def set_summary(self, summary):
        """set_summary(str)

        Sets summary to text provided
        """
        self._event.summary.value = summary

    def get_start_datetime(self):
        """get_start_datetime() -> datetime.datetime or datetime.date

        This returns start date of the event or datetime in case time
        is included. This should probably be fixed to return datetime
        always."""
        return self._event.dtstart.value

    def set_start_datetime(self, dt):
        """set_start_datetime(dt)

        Sets start datetime to provided datetime.datetime instance"""
        self._event.dtstart.value = dt

    def get_end_datetime(self):
        """get_end_datetime() -> datetime.datetime or datetime.date

        This returns end date of the event or datetime in case time
        is included. This should probably be fixed to return datetime
        always."""
        return self._event.dtend.value

    def set_end_datetime(self, dt):
        """set_end_datetime(dt)

        Sets end datetime to provided datetime.datetime instance"""
        self._event.dtend.value = dt

    def get_description(self):
        """get_description() -> str

        Returns long description of the event"""
        event = self._event
        return event['DESCRIPTION']

    def set_description(self, description):
        """set_description(description)

        Sets long description of the event"""
        self._event['DESCRIPTION'] = description

    def get_location(self):
        """get_location() -> str

        Returns event location text (where it is going to happen)"""
        return self._event.location.value

    def set_location(self, location):
        """set_location(location)

        Sets location text of the event"""
        self._event.location.value = location

    def get_url(self):
        """get_url() -> str

        Returns event url text"""
        return self._event.url.value

    def set_url(self, url):
        """set_url(location)

        Sets url text of the event"""
        self._event.url.value = url

    def get_attendees(self):
        """get_attendees() -> [Attendee]

        Returns list of Attendee classes representing event attendees
        and their statuses"""
        ret = []
        for at in self._event.attendee_list:
            ret.append(Attendee(at))
        return ret

    def set_attendees(self, atlist):
        self._event.attendee_list = atlist

    def get_rrule(self):
        """get_rrule(uid) -> dateutil.rrule

        Returns RRULE defined for given event or None if
        no RRULE has been defined

        uid - Event UID for which rrule should be returned
        """
        try:
            ret = None
            rrule_str = self.get_rrule_str(self.uid)
            rule_parts = rrule_str.split(';')
            fixed_rrule = ""
            for part in rule_parts:
                if part.startswith('UNTIL') and len(part) == 14:
                    part = "%s000000" % part
                fixed_rrule.append(part + ";")

            ret = rrulestr(fixed_rrule, dtstart=self.get_start_datetime())
        except ValueError:
            pass
        finally:
            return ret

    def get_rrule_str(self):
        """get_rrule_str(uid) -> string

        Returns string representation of repeat rule for given event
        """
        return str(self._event['RRULE'])


class Attendee(object):

    possible_params = [('CN', 'name'),
                       ('ROLE', 'role'),
                       ('RSVP', 'rsvp_request'),
                       ('PARTSTAT','rsvp_status'),
        ]


    def __init__(self, ical_attendee):
        self.address = ical_attendee.value
        self.__ical = ical_attendee
        self.params = self.__ical.params
        for a, b in self.possible_params:
            self.__set_param(a, b)

    def __set_param(self, paramname, propname=None):
        if self.params.has_key(paramname):
            if not propname:
                propname = paramname
            setattr(self, propname, self.params[paramname][0])

    def __str__(self):
        return self.__ical.serialize()

class ConnID(object):
    """Class that holds unique connection ID so that we can identify connections"""

    def __init__(self, url, login = None):
        digest = hashlib.md5()
        digest.update(url)
        if login:
            digest.update(login)

        self.digest = digest.hexdigest()
        self.url = url
        self.login = login

import datetime
from pyical import WebCal
from dateutil.tz import tzical, gettz

url = 'http://www.google.com/calendar/ical/9e11j73ff4pdomjlort7v10h640okf47%40import.calendar.google.com/public/basic.ics'
wc = WebCal(url)
c = wc.get_calendar()
events = c.events_after(datetime.datetime.now(gettz()))

for date, e in events:
    print "%s: %s" % (date,
            e.get_summary().encode('utf-8'))

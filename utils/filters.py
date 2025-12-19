from config.bookmakers import UK_BOOKMAKERS

def filter_uk_books(events):
    """
    Filters Odds API events to UK bookmakers only.
    Drops events with no remaining bookmakers.
    """
    filtered_events = []

    for event in events:
        uk_books = [
            b for b in event.get("bookmakers", [])
            if b.get("key") in UK_BOOKMAKERS
        ]

        if not uk_books:
            continue

        event_copy = dict(event)
        event_copy["bookmakers"] = uk_books
        filtered_events.append(event_copy)

    return filtered_events

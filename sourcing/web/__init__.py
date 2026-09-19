# -*- coding: utf-8 -*-
"""Channel A2 -- the agencies' own websites, crawled deterministically.

Not to be confused with `matching.channel_b`, which is an AI agent reading a
handful of pages for one client on demand. This package does the opposite: it
sweeps every crawlable site on a schedule and stores whatever it finds, so a
client who walks in gets an answer out of the database instead of out of a
browser session.

The listing URL is the identity. It is what lets a second pass skip a page it
has already read, and what lets us ask later whether a listing is still up.
"""

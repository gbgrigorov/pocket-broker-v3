# -*- coding: utf-8 -*-
"""Separating a listing from the furniture around it.

The first crawl read "Студии До 55 000€" off a price-filter menu and stored it
as the asking price of three different flats. Every agency site carries this
hazard: navigation, filter sidebars, "similar properties" rails and footers are
all full of numbers that look exactly like the one we came for.

No parser library is used -- the project deliberately runs on Django and psycopg
alone -- so this walks stdlib's HTMLParser and drops whole subtrees whose tag or
class marks them as chrome. What survives is the listing.
"""
import html as html_lib
import json
import re
from html.parser import HTMLParser

# Tags whose entire contents are never listing data.
DROP_TAGS = {'script', 'style', 'noscript', 'nav', 'header', 'footer', 'aside',
             'form', 'select', 'button', 'iframe', 'svg', 'template', 'dialog'}

# Class or id fragments that mark a block as furniture. Matched on word-ish
# boundaries so "main-content" is not mistaken for a menu.
CHROME = re.compile(
    r'(?:^|[-_ ])(?:nav|navbar|menu|topbar|sidebar|side-?nav|filter|filters|'
    r'facet|footer|header|masthead|cookie|consent|modal|popup|overlay|drawer|'
    r'offcanvas|widget|related|similar|recommend|recently|viewed|carousel-nav|'
    r'newsletter|subscribe|social|share|breadcrumbs?|pagination|search-form|'
    r'compare|favorites?|izbrannoe|toolbar|banner)(?:$|[-_ ])', re.I)

H1_RAW = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S | re.I)
TAGS = re.compile(r'<[^>]+>')

VOID = {'br', 'img', 'input', 'meta', 'link', 'hr', 'source', 'area', 'base'}

# Structural roots are never furniture, whatever their classes say. WordPress
# themes put words like "header-transparent" on <body>, and treating that as a
# chrome marker discarded four entire sites.
NEVER_DROP = {'html', 'body', 'main', 'article'}
BLOCK = {'p', 'div', 'li', 'tr', 'br', 'h1', 'h2', 'h3', 'h4', 'section', 'td', 'th'}


class _Reader(HTMLParser):
    def __init__(self, strict=True):
        super().__init__(convert_charrefs=True)
        self.strict = strict
        self.parts = []
        self.ld = []
        self.og = {}
        self.title = ''
        self.h1 = ''
        self._stack = []          # open tags
        self._drop_at = None      # stack depth where a chrome subtree began
        self._in_title = False
        self._in_h1 = False
        self._in_ld = False
        self._ld_buffer = []

    @property
    def _drop(self):
        return self._drop_at is not None

    # -- structure ------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            prop = (attrs.get('property') or attrs.get('name') or '').lower()
            if prop.startswith('og:') and attrs.get('content'):
                self.og.setdefault(prop[3:], html_lib.unescape(attrs['content']))
            return
        if tag in VOID:
            # <br> is void, but it is also where a line ends. Without this the
            # spec table collapses into one line and "Етаж: Партер Общо етажи: 5"
            # becomes a single unreadable pair.
            if tag == 'br' and not self._drop:
                self.parts.append('\n')
            return

        self._stack.append(tag)
        if tag == 'script' and 'ld+json' in (attrs.get('type') or '').lower():
            self._in_ld, self._ld_buffer = True, []
        elif tag == 'title':
            self._in_title = True
        elif tag == 'h1' and not self._drop and not self.h1:
            self._in_h1 = True

        if self._drop or tag in NEVER_DROP:
            return
        marker = f"{attrs.get('class', '')} {attrs.get('id', '')}".strip()
        if tag in DROP_TAGS or (self.strict and marker and CHROME.search(marker)):
            # Anchored to the stack, not counted: pages close tags sloppily, and
            # a counter that drifts by one silently swallows the rest of the page.
            self._drop_at = len(self._stack) - 1

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag == 'title':
            self._in_title = False
        elif tag == 'h1':
            self._in_h1 = False
        elif tag == 'script' and self._in_ld:
            self._in_ld = False
            try:
                self.ld.append(json.loads(''.join(self._ld_buffer).strip()))
            except Exception:                                   # noqa: BLE001
                pass

        if tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass
        if self._drop and len(self._stack) <= self._drop_at:
            self._drop_at = None
        if tag in BLOCK and not self._drop:
            self.parts.append('\n')

    # -- text -----------------------------------------------------------
    def handle_data(self, data):
        if self._in_ld:
            self._ld_buffer.append(data)
            return
        if self._in_title:
            self.title += data
            return
        if self._drop:
            return
        if self._in_h1:
            self.h1 += data
        if data.strip():
            self.parts.append(data)

    def error(self, message):       # HTMLParser ABC leftover; never raise
        pass


def read(html, anchor=''):
    """Parse once. Returns {text, content, ld, og, title, h1}.

    `content` is the text from the listing's own heading downwards. Menus and
    filter rails sit above it on every site measured; the labelled facts sit
    below it on every one of them.
    """
    page = _parse(html, strict=True)
    # Some themes mark their main wrapper with a word this module reads as
    # furniture. If strict parsing left almost nothing behind, the markers were
    # wrong about the page, not the page about itself.
    if len(page['text']) < 300 and len(html) > 5000:
        loose = _parse(html, strict=False)
        if len(loose['text']) > len(page['text']):
            page = loose

    # A theme can bury its <h1> inside a wrapper this module reads as furniture.
    # The heading still exists in the markup, and it is the best anchor there is.
    if not page['h1']:
        match = H1_RAW.search(html)
        if match:
            page['h1'] = re.sub(r'\s+', ' ', html_lib.unescape(
                TAGS.sub(' ', match.group(1)))).strip()

    heading = page['h1'] or anchor or page['og'].get('title') or ''
    page['content'] = _window(page['text'], heading)
    return page


def _parse(html, strict=True):
    reader = _Reader(strict=strict)
    try:
        reader.feed(html)
        reader.close()
    except Exception:                                           # noqa: BLE001
        pass                       # malformed markup still yields what was read
    text = re.sub(r'[ \t]+', ' ', ''.join(reader.parts))
    text = re.sub(r'\n\s*\n+', '\n', text).strip()

    flat, stack = [], list(reader.ld)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            flat.append(node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)

    return {'text': text, 'content': text, 'ld': flat, 'og': reader.og,
            'title': re.sub(r'\s+', ' ', reader.title).strip(),
            'h1': re.sub(r'\s+', ' ', reader.h1).strip()}


def _window(text, heading):
    """Text from the heading down, or all of it when the heading is not found."""
    if heading and len(heading) > 8:
        at = text.find(heading[:40])
        if at > -1:
            return text[at:]
    return text

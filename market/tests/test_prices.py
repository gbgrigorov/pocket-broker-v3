# -*- coding: utf-8 -*-
"""A €/m² quote is not an asking price. 28% of sale offers were stored as if
it were, and every one of them looked plausible on its own."""
from django.test import SimpleTestCase

from market import prices


class PerSquareMetreTests(SimpleTestCase):
    def test_recognises_the_unit_in_several_spellings(self):
        for raw in ('€ 1 019 /m2', '1019 €/m²', '1 019 € / кв.м', '1019 EUR/кв. м',
                    '€1019 per sq m'):
            with self.subTest(raw=raw):
                self.assertTrue(prices.is_per_m2(raw), raw)

    def test_a_plain_total_is_not_a_per_metre_quote(self):
        for raw in ('125 000 €', '€ 245 000', '244 478 лв.', '1 019 €'):
            with self.subTest(raw=raw):
                self.assertFalse(prices.is_per_m2(raw), raw)

    def test_derives_the_total_from_the_area(self):
        total, per_m2 = prices.normalise(1019.0, 108.0, '€ 1 019 /m2')
        self.assertEqual(per_m2, 1019.0)
        self.assertEqual(total, 110052.0)

    def test_without_an_area_the_total_stays_unknown(self):
        """Never invented -- the same rule the search applies to every gap."""
        total, per_m2 = prices.normalise(1019.0, None, '€ 1 019 /m2')
        self.assertIsNone(total)
        self.assertEqual(per_m2, 1019.0)

    def test_a_plain_total_is_left_alone_and_gains_a_per_metre_figure(self):
        total, per_m2 = prices.normalise(110052.0, 108.0, '110 052 €')
        self.assertEqual(total, 110052.0)
        self.assertEqual(per_m2, 1019.0)

    def test_a_cheap_listing_is_not_assumed_to_be_a_per_metre_quote(self):
        """A €14 000 parking space is real. Magnitude is not evidence."""
        total, _per = prices.normalise(14000.0, 14.0, '14 000 €')
        self.assertEqual(total, 14000.0)


class MultiLinePriceTests(SimpleTestCase):
    """roneva renders the complex name directly above the price, so
    "Възраждане 4" + "185 000 €" was stored as 4 185 000 € — a €185k flat at
    €4.19m. 43 offers were wrong that way, and the UI is what made it obvious:
    31 705 €/m² is impossible in Varna."""

    def test_picks_the_line_carrying_the_currency(self):
        self.assertEqual(prices.price_line('4\n185000 €'), '185000 €')
        self.assertEqual(prices.price_line('Възраждане 2\n415 000 €'), '415 000 €')

    def test_a_single_line_price_is_left_alone(self):
        self.assertIsNone(prices.price_line('185 000 €'))
        self.assertIsNone(prices.price_line(''))

    def test_reads_the_number_through_thousand_spaces(self):
        self.assertEqual(prices.value_of('185 000 €'), 185000.0)
        self.assertEqual(prices.value_of('1 019 €/m2'), 1019.0)
        self.assertEqual(prices.value_of('244 478 лв.'), 244478.0)

    def test_falls_back_to_the_longest_digit_run_without_a_currency(self):
        self.assertEqual(prices.price_line('4\n185000'), '185000')

    def test_gives_up_rather_than_guessing(self):
        """Two currency lines is ambiguous; the stored value stands."""
        self.assertIsNone(prices.price_line('100 €\n200 €'))

    def test_a_three_digit_group_after_a_dot_is_a_thousand_mark(self):
        """185.000 is 185 000, not 185."""
        self.assertEqual(prices.value_of('185.000 €'), 185000.0)

    def test_a_real_decimal_survives(self):
        self.assertEqual(prices.value_of('1 019.50 €'), 1019.5)

# -*- coding: utf-8 -*-
"""Vendored broker-crm modules, kept at their upstream paths.

Only three files live here -- dedup, features and geo -- and they keep the
package name they had in broker-crm so that `from crm import features`, as the
vendored crawler writes it, resolves without editing a single vendored line.
Renaming the package would have been the first divergence, and the cheapest one
to avoid.

This is not a CRM and nothing here manages clients. Our own code is in market/.
"""

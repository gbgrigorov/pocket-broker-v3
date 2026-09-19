# -*- coding: utf-8 -*-
"""New-build detection, and the milestone trap.

"Пред Акт 16" means the building has NOT reached Акт 16. Reading it as a
finished building would tell a buyer they can move in, when in fact they are
buying off-plan — the single most consequential misreading in this market.
"""
from django.test import SimpleTestCase

from market import newbuild


class StageTests(SimpleTestCase):
    def test_pre_act_beats_the_milestone_it_contains(self):
        key, label = newbuild.stage_of('Пред Акт 16. В най-добрата част на Аспарухово')
        self.assertEqual(key, 'pre_act16')
        self.assertEqual(label, 'Пред Акт 16')

    def test_reads_each_milestone(self):
        for text, expected in (('✨ АКТ 14 ✨ ОАЗИС 5', 'act14'),
                               ('сграда с Акт 15', 'act15'),
                               ('АКТ-16, готов за нанасяне', 'act16'),
                               ('акт16', 'act16')):
            with self.subTest(text=text):
                self.assertEqual(newbuild.stage_of(text)[0], expected)

    def test_no_milestone_is_none(self):
        self.assertEqual(newbuild.stage_of('Тристаен в Чайка'), (None, None))


class NewBuildTests(SimpleTestCase):
    def test_recognises_the_phrases_agencies_use(self):
        for text in ('Лукс Ново Строителство/ Морска Гледка', 'новостроящ се комплекс',
                     'апартамент в строеж', 'покупка на зелено', 'до ключ',
                     'new construction in Varna'):
            with self.subTest(text=text):
                self.assertTrue(newbuild.is_new_build(text), text)

    def test_a_milestone_alone_marks_it_as_new(self):
        self.assertTrue(newbuild.is_new_build('Пред Акт 16'))

    def test_an_ordinary_resale_is_not_new(self):
        self.assertFalse(newbuild.is_new_build('Тристаен тухлен апартамент в Левски'))
        self.assertFalse(newbuild.is_new_build(''))

    def test_describe_returns_all_three(self):
        is_new, key, label = newbuild.describe('Пред АКТ 14 / ЮГ')
        self.assertTrue(is_new)
        self.assertEqual(key, 'pre_act14')
        self.assertEqual(label, 'Пред Акт 14')

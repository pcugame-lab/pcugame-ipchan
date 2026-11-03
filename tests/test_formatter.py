import unittest
from app.data import IPEntry, UserRecord
from app.formatter import build_status_pages, _width

class FormatterTests(unittest.TestCase):
    def entries(self, count=30):
        return [(UserRecord(1, 'test', 'test'), IPEntry(
            f'203.250.133.{i+1}', '긴 기기 이름 macbook 노트북' * 3,
            '228805이승엽', 'auto' if i % 2 else 'manual',
            '2026-11-03T00:00:00', '')) for i in range(count)]

    def test_table_alignment_and_limits(self):
        pages = build_status_pages(self.entries(), '203.250.133')
        self.assertGreater(len(pages), 1)
        text = '\n'.join(p.fields[0].value for p in pages)
        for i in range(30):
            self.assertEqual(text.count(f'`203.250.133.{i+1}`'), 1)
        for p in pages:
            self.assertLessEqual(len(p), 6000)
            self.assertEqual(len(p.fields), 3)
            counts = []
            for field in p.fields:
                self.assertTrue(field.inline)
                self.assertLessEqual(len(field.value), 1024)
                lines = field.value.splitlines()
                self.assertTrue(all(line.startswith('`') and line.count('`') == 2 for line in lines))
                counts.append(len(lines))
            self.assertEqual(len(set(counts)), 1)

    def test_mobile_boxes_and_pagination(self):
        pages = build_status_pages(self.entries(16), '203.250.133', mobile=True)
        self.assertEqual(len(pages), 4)
        self.assertIn('IP: 1\n', pages[0].description)
        self.assertNotIn('203.250.133.', pages[0].description)
        self.assertIn('203.250.133.x', pages[0].title)
        for p in pages:
            self.assertLessEqual(p.description.count('```'), 10)
            self.assertIn('등록일: 2026-11-03', p.description)
            self.assertTrue(all(_width(line) <= 26 for line in p.description.splitlines()))

    def test_code_fence_and_newline_input(self):
        entries = self.entries(1)
        entries[0][1].person_name = 'hello```\n@everyone'
        for mobile in [False, True]:
            page = build_status_pages(entries, '203.250.133', mobile)[0]
            text = page.description if mobile else page.fields[1].value
            self.assertEqual(text.count('```'), 2 if mobile else 0)
            self.assertIn('helloˋˋˋ', text)

    def test_empty(self):
        for mobile in [False, True]:
            pages = build_status_pages([], '203.250.133', mobile)
            self.assertEqual(len(pages), 1)
            self.assertIn('없습니다', pages[0].description)

class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_toggle_and_navigation(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.formatter import StatusView
        entries = FormatterTests().entries(16)
        table = build_status_pages(entries, '203.250.133')
        mobile = build_status_pages(entries, '203.250.133', True)
        view = StatusView(table, mobile)
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
        await view.btn_layout.callback(interaction)
        self.assertIs(view.pages, mobile)
        self.assertEqual(view.btn_layout.label, '표 보기')
        self.assertTrue(view.btn_prev.disabled)
        await view.btn_next.callback(interaction)
        self.assertEqual(view.page, 1)
        await view.btn_layout.callback(interaction)
        self.assertIs(view.pages, table)
        self.assertEqual(view.page, 0)
        self.assertEqual(view.btn_layout.label, '모바일 보기')
        view.stop()

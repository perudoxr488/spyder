import importlib
import contextlib
import io
import os
import sys
import unittest

os.environ.setdefault("TOKEN_BOT", "123:test")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("API_BASE", "http://127.0.0.1:8080")


class FakeApplication:
    def __init__(self):
        self.handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)


class RequestCatalogSmokeTest(unittest.TestCase):
    def test_request_catalog_has_expected_commands(self):
        from comandos.request_catalog import REQUEST_COMMANDS

        names = [item[0] for item in REQUEST_COMMANDS]
        self.assertEqual(len(names), 68)
        self.assertEqual(len(set(names)), 68)
        self.assertIn("dni", names)
        self.assertIn("ruc", names)
        self.assertIn("facial", names)

    def test_main_registers_all_request_commands(self):
        sys.modules.pop("main", None)
        with contextlib.redirect_stdout(io.StringIO()):
            main = importlib.import_module("main")
        fake_app = FakeApplication()

        main.register_request_commands(fake_app)

        self.assertEqual(len(fake_app.handlers), len(main.REQUEST_COMMANDS))
        registered = {next(iter(handler.commands)) for handler in fake_app.handlers}
        expected = {item[0] for item in main.REQUEST_COMMANDS}
        self.assertEqual(registered, expected)


if __name__ == "__main__":
    unittest.main()

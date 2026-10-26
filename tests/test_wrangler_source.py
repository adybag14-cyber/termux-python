import unittest

from scripts.resolve_wrangler_source import parse_source_tags, select_source


class WranglerSourceTests(unittest.TestCase):
    def package(self, version):
        return {"name": "wrangler", "version": version}

    def test_annotated_tags_are_peeled_and_prereleases_ignored(self):
        tags = parse_source_tags(
            f"{'a' * 40}\trefs/tags/wrangler@4.153.0\n"
            f"{'b' * 40}\trefs/tags/wrangler@4.153.0^{{}}\n"
            f"{'c' * 40}\trefs/tags/wrangler@4.154.0-beta.1\n"
            f"{'d' * 40}\trefs/tags/wrangler@4.151.3\n"
        )
        self.assertEqual(tags, {"4.153.0": "b" * 40, "4.151.3": "d" * 40})

    def test_latest_available_release_is_pinned(self):
        result = select_source("4.153.0", {"4.153.0": "b" * 40}, self.package)
        self.assertEqual(result["source_commit"], "b" * 40)
        self.assertFalse(result["fallback"])

    def test_npm_release_without_git_tag_uses_newest_published_source(self):
        tags = {"4.151.2": "a" * 40, "4.151.3": "b" * 40, "4.153.0": "c" * 40}
        result = select_source("4.152.0", tags, self.package)
        self.assertEqual(result["version"], "4.151.3")
        self.assertEqual(result["requested_version"], "4.152.0")
        self.assertTrue(result["fallback"])

    def test_unpublished_source_tag_is_skipped(self):
        result = select_source(
            "4.153.0", {"4.153.0": "a" * 40, "4.152.0": "b" * 40},
            lambda version: None if version == "4.153.0" else self.package(version),
        )
        self.assertEqual(result["version"], "4.152.0")

    def test_registry_mismatch_and_network_failures_do_not_silently_downgrade(self):
        tags = {"4.153.0": "a" * 40}
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            select_source("4.153.0", tags, lambda _: self.package("4.152.0"))
        def unavailable(_):
            raise OSError("registry unavailable")
        with self.assertRaises(OSError):
            select_source("4.153.0", tags, unavailable)

    def test_missing_stable_source_and_cross_major_fallback_fail(self):
        for tags in ({}, {"3.99.0": "a" * 40}, {"4.154.0": "b" * 40}):
            with self.subTest(tags=tags), self.assertRaisesRegex(RuntimeError, "No published stable"):
                select_source("4.153.0", tags, self.package)
        with self.assertRaises(ValueError):
            select_source("4.153.0-beta.1", {}, self.package)

    def test_conflicting_source_refs_fail(self):
        with self.assertRaisesRegex(RuntimeError, "Conflicting source"):
            parse_source_tags(
                f"{'a' * 40}\trefs/tags/wrangler@4.153.0\n"
                f"{'b' * 40}\trefs/tags/wrangler@4.153.0\n"
            )


if __name__ == "__main__":
    unittest.main()

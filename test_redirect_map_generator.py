import os
import unittest

from redirect_map_generator import build_map, load_urls, norm_path, render, score

HERE = os.path.dirname(os.path.abspath(__file__))


class Tests(unittest.TestCase):
    def setUp(self):
        self.old = load_urls(os.path.join(HERE, "examples", "old-urls.txt"))
        self.new = load_urls(os.path.join(HERE, "examples", "new-urls.txt"))
        self.rows = {r["old_path"]: r for r in build_map(self.old, self.new)}

    def test_norm_path(self):
        self.assertEqual(norm_path("https://x.com/Blog/Post/"), "/blog/post")
        self.assertEqual(norm_path("https://x.com/a/index.html"), "/a")
        self.assertEqual(norm_path("https://x.com"), "/")

    def test_unchanged_urls_skipped(self):
        self.assertNotIn("/", self.rows)

    def test_matches(self):
        self.assertEqual(self.rows["/contact.php"]["new_path"], "/contact")
        self.assertEqual(self.rows["/services/drain-cleaning.html"]["new_path"], "/drain-cleaning")
        self.assertEqual(self.rows["/services/water-heater-installation.html"]["new_path"],
                         "/water-heaters/installation")
        self.assertEqual(self.rows["/blog/2020/01/tankless-water-heater-cost-guide"]["new_path"],
                         "/blog/tankless-water-heater-cost")

    def test_parent_fallback(self):
        r = self.rows["/blog/2018/03/company-picnic-photos"]
        self.assertEqual((r["method"], r["new_path"], r["review"]), ("parent", "/blog", "yes"))

    def test_score_order(self):
        self.assertGreater(score("/services/drain-cleaning.html", "/drain-cleaning"),
                           score("/services/drain-cleaning.html", "/contact"))

    def test_render_formats(self):
        rows = list(self.rows.values())
        ht = render(rows, "htaccess")
        self.assertIn("RewriteRule ^contact\\.php/?$ /contact/ [R=301,L]", ht)
        self.assertIn("location ~* ^/contact\\.php/?$ { return 301 /contact/; }", render(rows, "nginx"))
        self.assertIn("/contact.php  /contact/  301", render(rows, "netlify"))
        self.assertIn('"permanent": true', render(rows, "vercel"))
        self.assertIn("/contact.php,/contact/,0,301", render(rows, "wordpress"))
        self.assertIn("https://example.com/contact/", render(rows, "netlify", absolute=True))


if __name__ == "__main__":
    unittest.main()

# Redirect Map Generator

Build a 301 redirect map for a site migration or URL restructure in seconds, instead of matching hundreds of URLs by hand in a spreadsheet.

Give it the old URLs and the new URLs. For every old URL that no longer exists it finds the best new match by slug and path similarity, falls back to the closest parent folder (or the home page), and flags weak matches for you to review. Then it writes the redirects in the format your server needs.

* Zero dependencies, one Python file (3.8+)
* Inputs: live sitemap URL, sitemap index, `.xml` / `.xml.gz` file, or a `.txt` / `.csv` URL list
* Matches across folder changes: `/services/water-heater-installation.html` → `/water-heaters/installation/`
* Skips URLs that didn't change
* Output: review CSV + `.htaccess`, Nginx, Netlify / Cloudflare Pages `_redirects`, Vercel JSON, or WordPress Redirection plugin CSV

## Usage

```bash
# old site sitemap vs new staging sitemap
python redirect_map_generator.py https://old.example.com/sitemap.xml https://staging.example.com/sitemap.xml

# lists exported from Screaming Frog, plus server configs
python redirect_map_generator.py old-urls.txt new-urls.txt --format htaccess --format nginx

# domain move: write absolute target URLs
python redirect_map_generator.py old.xml new.xml --absolute --format netlify
```

Try it on the included example:

```
$ python redirect_map_generator.py examples/old-urls.txt examples/new-urls.txt -o -

old,new,score,method,review
https://example.com/about-us.html,https://example.com/about/,0.636,match,yes
https://example.com/services/water-heater-installation.html,https://example.com/water-heaters/installation/,0.953,match,
https://example.com/services/drain-cleaning.html,https://example.com/drain-cleaning/,0.952,match,
https://example.com/blog/2020/01/tankless-water-heater-cost-guide/,https://example.com/blog/tankless-water-heater-cost/,0.793,match,
https://example.com/blog/2018/03/company-picnic-photos/,https://example.com/blog/,0.0,parent,yes
https://example.com/contact.php,https://example.com/contact/,0.97,match,
```

## Options

| Option | Default | What it does |
|---|---|---|
| `-o FILE` | `redirects.csv` | Review CSV, `-` for stdout |
| `--format NAME` | | `htaccess`, `nginx`, `netlify`, `vercel`, `wordpress`; repeatable |
| `--threshold N` | 0.6 | Minimum score to accept a match |
| `--review-below N` | 0.75 | Flag matches under this score |
| `--absolute` | off | Use full target URLs (cross domain moves) |

## Output files

| Format | File | Where it goes |
|---|---|---|
| `htaccess` | `.htaccess` | Apache / most shared WordPress hosting, above the WordPress block |
| `nginx` | `redirects.nginx.conf` | `include` it inside your `server {}` block |
| `netlify` | `_redirects` | Site root on Netlify or Cloudflare Pages |
| `vercel` | `vercel.redirects.json` | Merge into `vercel.json` |
| `wordpress` | `redirection-import.csv` | Redirection plugin → Import |

## Before you go live

1. Open the CSV and check every row marked `review = yes`. Fallbacks to a parent folder or the home page are a last resort; a real match is always better.
2. Redirect each old URL straight to its final URL, with no chains.
3. After launch, crawl the old URL list and confirm every one returns a single 301 to a 200 page.

## Tests

```bash
python -m unittest -v
```

## License

MIT

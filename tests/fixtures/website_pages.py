from __future__ import annotations

from datetime import UTC, datetime

from vyro_growth.providers.website import PublicPage

VERIFIED_HOME_HTML = """
<html>
  <head><title>Austin Family Medicine PLLC</title></head>
  <body>
    <h1>Austin Family Medicine PLLC</h1>
    <p>Serving families in Austin, TX.</p>
    <p>Our services include family medicine and pediatrics.</p>
    <p>We are an independently owned practice with 3 physicians.</p>
    <p>Call us at <a href="tel:5125550100">(512) 555-0100</a></p>
    <p>Email <a href="mailto:info@austinfamilymedicine.com">info@austinfamilymedicine.com</a></p>
    <p><a href="/contact">Contact us</a></p>
    <p>In-house billing questions can be sent to the front desk.</p>
  </body>
</html>
"""

WRONG_CITY_HTML = """
<html>
  <body>
    <h1>Austin Family Medicine PLLC</h1>
    <p>Now seeing patients in Dallas, TX only.</p>
  </body>
</html>
"""

UNRELATED_HTML = """
<html>
  <body>
    <h1>Sunrise Coffee Roasters</h1>
    <p>Best beans in Seattle, WA.</p>
  </body>
</html>
"""

DIRECTORY_HTML = """
<html>
  <body>
    <h1>Healthgrades physician directory</h1>
    <p>Austin Family Medicine PLLC is one of 400 listings in Austin, TX.</p>
  </body>
</html>
"""

NAME_ONLY_HTML = """
<html>
  <body>
    <h1>Austin Family Medicine PLLC</h1>
    <p>Welcome to our website.</p>
  </body>
</html>
"""

NO_OPTIONAL_FACTS_HTML = """
<html>
  <body>
    <h1>Austin Family Medicine PLLC</h1>
    <p>Proudly serving Austin, TX.</p>
  </body>
</html>
"""

ROSTER_HTML = """
<html>
  <body>
    <h1>Austin Family Medicine PLLC</h1>
    <p>Proudly serving Austin, TX.</p>
    <h2>Our Team</h2>
    <ul>
      <li>Jane Example, MD</li>
      <li>John Example, DO</li>
      <li>Alex Example, NP</li>
    </ul>
  </body>
</html>
"""

REVIEW_HTML = """
<html>
  <body>
    <h1>Reviews</h1>
    <p>The doctor helped my diabetes and prescribed medication.</p>
  </body>
</html>
"""

SECOND_VERIFIED_HTML = """
<html>
  <body>
    <h1>Austin Family Medicine PLLC</h1>
    <p>Visit our other site. We care for families in Austin, TX.</p>
    <p>Family medicine clinic.</p>
  </body>
</html>
"""


def page(url: str, html_text: str) -> PublicPage:
    return PublicPage(
        url=url,
        status_code=200,
        content_type="text/html",
        text=html_text,
        fetched_at=datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
    )

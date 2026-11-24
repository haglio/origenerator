from __future__ import annotations

from app_support import haglio_settings
from app_support.gallery_records import IMAGE, VIDEO, recorded_block
from app_support.site_pages import page_address

from origenerator.media import MediaType

SETTING = "site_pages"


def _pages_of(site: str) -> dict:
    try:
        pages = haglio_settings.value(SETTING, site)
    except haglio_settings.MissingSetting:
        return {}
    return pages if isinstance(pages, dict) else {}


def makes_images(site: str) -> bool:
    return bool(_pages_of(site).get(IMAGE))


def address_asking_for_an_image(site: str, params: dict) -> str:
    pages = _pages_of(site)
    return page_address({"source_image": recorded_block(params, MediaType.IMAGE)},
                        image_page=pages[IMAGE], video_page=pages.get(VIDEO, ""), submit=True)

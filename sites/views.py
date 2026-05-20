import httpx
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.http import HttpResponse
from django.middleware.csrf import get_token

from .utils import aget_current_site_attributes


def rewrite_root_asset_urls(html: str, *, cdn_domain: str, frontend_folder: str) -> str:
    base_url = f"https://{cdn_domain}/{frontend_folder}" if frontend_folder else f"https://{cdn_domain}"
    asset_prefixes = (
        "assets/",
        "images/",
        "favicon",
        "manifest",
        "site.webmanifest",
        "vite.svg",
    )
    for attribute in ("href", "src"):
        for prefix in asset_prefixes:
            html = html.replace(f'{attribute}="/{prefix}', f'{attribute}="{base_url}/{prefix}')
    return html


async def serve_index(request, resource):
    # Check if requested type is JSON - in this case the error is likely 404
    if "application/json" in (request.META.get("HTTP_ACCEPT") or []):
        return HttpResponse(status=404)

    site_attributes = await aget_current_site_attributes(request)
    if not site_attributes:
        return HttpResponse("Site not found.", status=404)

    site_s3_folder = site_attributes.s3_frontend_folder.strip().strip("/")
    site_s3_domain = site_attributes.s3_custom_domain.strip()
    if site_s3_folder and not site_s3_domain:
        return HttpResponse(
            "Deployment site is missing a public asset domain. Run deployment site sync again.",
            status=500,
        )
    if not site_s3_domain:
        site_s3_domain = settings.AWS_S3_CUSTOM_DOMAIN.strip()
    cache_key = f"index_html_cache_{site_s3_domain}_{site_s3_folder}"
    cache_timeout = 10  # Cache timeout in seconds

    # Attempt to get the cached content asynchronously
    cached_content = await cache.aget(cache_key)
    if cached_content:
        response = HttpResponse(cached_content, content_type="text/html")
    else:
        # Fetch the content using httpx
        async with httpx.AsyncClient() as client:
            try:
                frontend_path = f"{site_s3_folder}/index.html" if site_s3_folder else "index.html"
                url = f"https://{site_s3_domain}/{frontend_path}"
                response = await client.get(url)
                response.raise_for_status()
                file_contents = rewrite_root_asset_urls(
                    response.text,
                    cdn_domain=site_s3_domain,
                    frontend_folder=site_s3_folder,
                )

                # Cache the fetched content asynchronously
                await cache.aset(cache_key, file_contents, cache_timeout)

                response = HttpResponse(file_contents, content_type="text/html")
            except httpx.HTTPStatusError as e:
                return HttpResponse(
                    f"Error fetching index.html from S3: {e}",
                    status=e.response.status_code,
                )

    # Manually ensure a CSRF token is generated and set the CSRF cookie
    get_token(request)
    return response


def csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})

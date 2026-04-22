from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.config import Settings
from app.db.models import AssetDirectory
from app.services.platform_service import PlatformService


def create_admin_ui_router(settings: Settings, session_factory: sessionmaker[Session]) -> APIRouter:
    router = APIRouter()
    platform = PlatformService(settings)

    def open_session() -> Session:
        return session_factory()

    async def form_body(request: Request) -> dict[str, str | list[str]]:
        parsed = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
        result: dict[str, str | list[str]] = {}
        for key, values in parsed.items():
            result[key] = values if len(values) > 1 else values[0]
        return result

    def require_admin(request: Request) -> bool:
        return verify_admin_cookie(request.cookies.get("ga4_admin_session"), settings.admin_session_secret)

    def login_redirect() -> RedirectResponse:
        return RedirectResponse("/admin/login", status_code=303)

    def redirect(path: str) -> RedirectResponse:
        return RedirectResponse(path, status_code=303)

    @router.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse("/admin", status_code=303)

    @router.get("/admin/login")
    async def login_page(request: Request) -> Response:
        if require_admin(request):
            return redirect("/admin")
        return HTMLResponse(render_login())

    @router.post("/admin/login")
    async def login(request: Request) -> Response:
        body = await form_body(request)
        if str(body.get("password") or "") != settings.admin_ui_password:
            return HTMLResponse(render_login("Invalid password"), status_code=401)
        response = redirect("/admin")
        response.set_cookie(
            "ga4_admin_session",
            sign_admin_cookie(settings.admin_session_secret),
            httponly=True,
            samesite="lax",
            secure=settings.app_env == "production",
            path="/",
        )
        return response

    @router.post("/admin/logout")
    async def logout() -> Response:
        response = redirect("/admin/login")
        response.delete_cookie("ga4_admin_session", path="/")
        return response

    @router.get("/admin")
    async def dashboard(request: Request) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            return HTMLResponse(
                layout(
                    "Dashboard",
                    render_dashboard(
                        client_count=len(platform.list_clients(session)),
                        source_count=len(platform.list_sources(session)),
                        asset_count=len(platform.list_assets(session)),
                    ),
                )
            )

    @router.get("/admin/clients")
    async def clients(request: Request) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            return HTMLResponse(layout("Clients", render_clients(platform.list_clients(session))))

    @router.post("/admin/clients")
    async def create_client(request: Request) -> Response:
        if not require_admin(request):
            return login_redirect()
        body = await form_body(request)
        with open_session() as session:
            platform.create_client(
                session,
                slug=str(body.get("slug") or ""),
                display_name=str(body.get("display_name") or ""),
                description=str(body.get("description") or ""),
            )
        return redirect("/admin/clients")

    @router.get("/admin/clients/{client_slug}")
    async def client_detail(request: Request, client_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            return HTMLResponse(render_client_detail_page(settings, platform, session, client_slug))

    @router.post("/admin/clients/{client_slug}")
    async def update_client(request: Request, client_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        body = await form_body(request)
        with open_session() as session:
            platform.update_client(
                session,
                client_slug,
                display_name=str(body.get("display_name") or ""),
                description=str(body.get("description") or ""),
                status=str(body.get("status") or "active"),
                default_property_id=str(body.get("default_property_id") or "") or None,
            )
        return redirect(f"/admin/clients/{client_slug}")

    @router.post("/admin/clients/{client_slug}/delete")
    async def delete_client(request: Request, client_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            platform.delete_client(session, client_slug)
        return redirect("/admin/clients")

    @router.post("/admin/clients/{client_slug}/properties")
    async def update_client_properties(request: Request, client_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        body = await form_body(request)
        raw_ids = body.get("property_ids") or []
        property_ids = raw_ids if isinstance(raw_ids, list) else [str(raw_ids)] if raw_ids else []
        with open_session() as session:
            platform.set_client_properties(
                session,
                client_slug=client_slug,
                property_ids=[str(item) for item in property_ids],
                default_property_id=str(body.get("default_property_id") or "") or None,
            )
        return redirect(f"/admin/clients/{client_slug}")

    @router.post("/admin/clients/{client_slug}/rotate-bearer")
    async def rotate_bearer(request: Request, client_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            token = platform.rotate_bearer_token(session, client_slug)
            return HTMLResponse(render_client_detail_page(settings, platform, session, client_slug, issued_token=token))

    @router.post("/admin/clients/{client_slug}/enable-public")
    async def enable_public(request: Request, client_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            token = platform.enable_public_token(session, client_slug)
            urls = platform.build_mcp_urls(client_slug, token)
            return HTMLResponse(render_client_detail_page(settings, platform, session, client_slug, public_url=urls["public_url"]))

    @router.post("/admin/clients/{client_slug}/disable-public")
    async def disable_public(request: Request, client_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            platform.disable_public_token(session, client_slug)
        return redirect(f"/admin/clients/{client_slug}")

    @router.get("/admin/sources")
    async def sources(request: Request) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            return HTMLResponse(layout("Sources", render_sources(platform.list_sources(session))))

    @router.post("/admin/sources")
    async def create_source(request: Request) -> Response:
        if not require_admin(request):
            return login_redirect()
        body = await form_body(request)
        with open_session() as session:
            platform.save_source(
                session,
                slug=str(body.get("slug") or ""),
                display_name=str(body.get("display_name") or ""),
                client_id=str(body.get("client_id") or ""),
                client_secret=str(body.get("client_secret") or ""),
                refresh_token=str(body.get("refresh_token") or ""),
                status=str(body.get("status") or "active"),
            )
        return redirect("/admin/sources")

    @router.post("/admin/sources/{source_slug}")
    async def update_source(request: Request, source_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        body = await form_body(request)
        with open_session() as session:
            platform.save_source(
                session,
                existing_slug=source_slug,
                slug=str(body.get("slug") or source_slug),
                display_name=str(body.get("display_name") or ""),
                client_id=str(body.get("client_id") or ""),
                client_secret=str(body.get("client_secret") or ""),
                refresh_token=str(body.get("refresh_token") or ""),
                status=str(body.get("status") or "active"),
            )
        return redirect("/admin/sources")

    @router.post("/admin/sources/{source_slug}/sync")
    async def sync_source(request: Request, source_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            try:
                result = await platform.sync_source(session, source_slug)
                message = f"Synced {result['synced_properties']} properties"
            except Exception as exc:
                message = f"Sync failed: {exc}"
            return HTMLResponse(layout("Sources", f"<div class='flash'>{escape(message)}</div>" + render_sources(platform.list_sources(session))))

    @router.post("/admin/sources/{source_slug}/delete")
    async def delete_source(request: Request, source_slug: str) -> Response:
        if not require_admin(request):
            return login_redirect()
        with open_session() as session:
            platform.delete_source(session, source_slug)
        return redirect("/admin/sources")

    return router


def sign_admin_cookie(secret: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 86400}).encode("utf-8")).decode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_admin_cookie(cookie: str | None, secret: str) -> bool:
    if not cookie or "." not in cookie:
        return False
    payload, signature = cookie.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
    except Exception:
        return False
    return int(data.get("exp", 0)) > int(time.time())


def layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#0b1117; --panel:#121b24; --line:#273746; --text:#f6f8fb; --muted:#9cb0c4; --accent:#34a853; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: ui-sans-serif, system-ui, sans-serif; background:#0b1117; color:var(--text); }}
    header {{ position:sticky; top:0; display:flex; justify-content:space-between; gap:16px; padding:16px 24px; background:rgba(11,17,23,.92); border-bottom:1px solid var(--line); }}
    main {{ max-width:1200px; margin:0 auto; padding:24px; }}
    a {{ color:#7bd88f; text-decoration:none; }}
    .nav {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
    .nav a, button, .button {{ border:1px solid var(--line); background:#172330; color:var(--text); border-radius:8px; padding:9px 12px; font-weight:700; cursor:pointer; }}
    button.primary, .button.primary {{ background:#1d6b36; border-color:#2e8b4d; }}
    button.danger {{ background:#4b1d27; border-color:#7d2f3e; }}
    .panel {{ border:1px solid var(--line); border-radius:8px; padding:18px; margin-bottom:18px; background:var(--panel); }}
    .grid {{ display:grid; gap:16px; }}
    .grid-2 {{ grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); }}
    .grid-3 {{ grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }}
    .muted {{ color:var(--muted); }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ text-align:left; padding:10px; border-bottom:1px solid var(--line); vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; }}
    input, textarea, select {{ width:100%; margin:8px 0 14px; padding:10px; border-radius:8px; border:1px solid var(--line); background:#0d1620; color:var(--text); }}
    label {{ display:block; font-weight:700; }}
    .check {{ display:flex; align-items:center; gap:10px; font-weight:500; }}
    .check input {{ width:auto; margin:0; }}
    .actions {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
    .code {{ white-space:pre-wrap; word-break:break-word; border:1px solid var(--line); border-radius:8px; padding:12px; background:#091018; margin:10px 0; }}
    .flash {{ border:1px solid #326d40; background:#102619; border-radius:8px; padding:12px; margin-bottom:16px; }}
  </style>
</head>
<body>
  <header>
    <strong>Google GA4 MCP</strong>
    <div class="nav">
      <a href="/admin">Dashboard</a>
      <a href="/admin/clients">Clients</a>
      <a href="/admin/sources">Sources</a>
      <form method="post" action="/admin/logout"><button type="submit">Logout</button></form>
    </div>
  </header>
  <main>{body}</main>
</body>
</html>"""


def render_login(error: str | None = None) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Login</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1117;color:white;font-family:ui-sans-serif,system-ui,sans-serif}}form{{width:min(420px,92vw);border:1px solid #273746;border-radius:8px;padding:24px;background:#121b24}}input,button{{width:100%;padding:12px;border-radius:8px;border:1px solid #273746;background:#0d1620;color:white;margin-top:10px}}button{{background:#1d6b36;font-weight:700}}</style></head>
<body><form method="post" action="/admin/login"><h1>Admin Login</h1><label>Password<input type="password" name="password" required></label><button type="submit">Login</button>{f'<p>{escape(error)}</p>' if error else ''}</form></body></html>"""


def render_dashboard(*, client_count: int, source_count: int, asset_count: int) -> str:
    return f"""
    <section class="panel"><h1>Dashboard</h1><p class="muted">Manage Google sources, GA4 assets, clients, and MCP access from this backend.</p></section>
    <section class="grid grid-3">
      <div class="panel"><div class="muted">Clients</div><h2>{client_count}</h2></div>
      <div class="panel"><div class="muted">Sources</div><h2>{source_count}</h2></div>
      <div class="panel"><div class="muted">GA4 Assets</div><h2>{asset_count}</h2></div>
    </section>
    """


def render_clients(clients: list) -> str:
    rows = "".join(
        f"<tr><td>{escape(client.slug)}</td><td>{escape(client.display_name)}</td><td>{escape(client.status.value)}</td><td><a href='/admin/clients/{escape(client.slug)}'>Open</a></td></tr>"
        for client in clients
    )
    return f"""
    <section class="panel"><h1>Clients</h1><table><thead><tr><th>Slug</th><th>Name</th><th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>
    <section class="panel"><h2>Create client</h2><form method="post" action="/admin/clients">
      <label>Slug<input name="slug" required></label>
      <label>Display name<input name="display_name" required></label>
      <label>Description<textarea name="description"></textarea></label>
      <button class="primary" type="submit">Create client</button>
    </form></section>
    """


def render_client_detail_page(
    settings: Settings,
    platform: PlatformService,
    session: Session,
    client_slug: str,
    *,
    issued_token: str | None = None,
    public_url: str | None = None,
) -> str:
    client = platform.get_client(session, client_slug)
    linked = {asset.property_id for asset in platform.list_client_properties(session, client.id)}
    assets = platform.list_assets(session)
    urls = platform.build_mcp_urls(client.slug)
    asset_rows = "".join(render_asset_checkbox(asset, linked, client.default_property_id) for asset in assets)
    token_block = f"<div class='code'>{escape(issued_token)}</div>" if issued_token else ""
    public_block = f"<div class='code'>{escape(public_url)}</div>" if public_url else ""
    body = f"""
    <section class="panel"><h1>{escape(client.display_name)}</h1><p class="muted">slug: {escape(client.slug)} · status: {escape(client.status.value)}</p></section>
    <section class="grid grid-2">
      <div class="panel"><h2>Edit client</h2><form method="post" action="/admin/clients/{escape(client.slug)}">
        <label>Display name<input name="display_name" value="{escape(client.display_name)}" required></label>
        <label>Description<textarea name="description">{escape(client.description or "")}</textarea></label>
        <label>Status<select name="status"><option value="active" {"selected" if client.status.value == "active" else ""}>active</option><option value="disabled" {"selected" if client.status.value == "disabled" else ""}>disabled</option></select></label>
        <input type="hidden" name="default_property_id" value="{escape(client.default_property_id or "")}">
        <button class="primary" type="submit">Save client</button>
      </form><form method="post" action="/admin/clients/{escape(client.slug)}/delete" style="margin-top:10px"><button class="danger" type="submit">Delete client</button></form></div>
      <div class="panel"><h2>MCP access</h2><p class="muted">Authenticated URL</p><div class="code">{escape(urls["authenticated_url"])}</div>{token_block}{public_block}
        <div class="actions">
          <form method="post" action="/admin/clients/{escape(client.slug)}/rotate-bearer"><button class="primary" type="submit">Rotate bearer token</button></form>
          <form method="post" action="/admin/clients/{escape(client.slug)}/enable-public"><button type="submit">Enable public link</button></form>
          <form method="post" action="/admin/clients/{escape(client.slug)}/disable-public"><button class="danger" type="submit">Disable public link</button></form>
        </div>
      </div>
    </section>
    <section class="panel"><h2>Connected GA4 assets</h2><form method="post" action="/admin/clients/{escape(client.slug)}/properties">
      <table><thead><tr><th>Use</th><th>Default</th><th>Property</th><th>Account</th><th>URI</th></tr></thead><tbody>{asset_rows}</tbody></table>
      <button class="primary" type="submit">Save assets</button>
    </form></section>
    """
    return layout(f"Client {client.slug}", body)


def render_asset_checkbox(asset: AssetDirectory, linked: set[str], default_property_id: str | None) -> str:
    checked = "checked" if asset.property_id in linked else ""
    default = "checked" if asset.property_id == default_property_id else ""
    return f"""<tr>
      <td><label class="check"><input type="checkbox" name="property_ids" value="{escape(asset.property_id)}" {checked}> Use</label></td>
      <td><input type="radio" name="default_property_id" value="{escape(asset.property_id)}" {default}></td>
      <td><strong>{escape(asset.display_name)}</strong><br><span class="muted">{escape(asset.property_id)} · {escape(", ".join(asset.measurement_ids or []))}</span></td>
      <td>{escape(asset.account_id or "")}</td>
      <td>{escape(asset.default_uri or "")}</td>
    </tr>"""


def render_sources(sources: list) -> str:
    rows = "".join(
        f"""<tr><td>{escape(source.slug)}</td><td>{escape(source.display_name)}</td><td>{escape(source.status.value)}</td><td>{escape(str(source.last_synced_at or ""))}</td><td>{escape(source.last_sync_error or "")}</td><td>
        <form class="actions" method="post" action="/admin/sources/{escape(source.slug)}/sync"><button class="primary" type="submit">Sync</button></form>
        <form method="post" action="/admin/sources/{escape(source.slug)}/delete"><button class="danger" type="submit">Delete</button></form></td></tr>
        <tr><td colspan="6"><form method="post" action="/admin/sources/{escape(source.slug)}"><div class="grid grid-2">
          <label>Slug<input name="slug" value="{escape(source.slug)}" required></label>
          <label>Display name<input name="display_name" value="{escape(source.display_name)}" required></label>
          <label>Status<select name="status"><option value="active" {"selected" if source.status.value == "active" else ""}>active</option><option value="disabled" {"selected" if source.status.value == "disabled" else ""}>disabled</option></select></label>
        </div><label>Google client ID<input name="client_id" placeholder="Leave blank to keep existing"></label><label>Google client secret<input type="password" name="client_secret" placeholder="Leave blank to keep existing"></label><label>Refresh token<input type="password" name="refresh_token" placeholder="Leave blank to keep existing"></label><button type="submit">Update source</button></form></td></tr>"""
        for source in sources
    )
    return f"""
    <section class="panel"><h1>Sources</h1><table><thead><tr><th>Slug</th><th>Name</th><th>Status</th><th>Last sync</th><th>Error</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>
    <section class="panel"><h2>Create source</h2><form method="post" action="/admin/sources">
      <div class="grid grid-2"><label>Slug<input name="slug" required></label><label>Display name<input name="display_name" required></label><label>Status<select name="status"><option value="active">active</option><option value="disabled">disabled</option></select></label></div>
      <label>Google client ID<input name="client_id" required></label>
      <label>Google client secret<input type="password" name="client_secret" required></label>
      <label>Refresh token<input type="password" name="refresh_token" required></label>
      <button class="primary" type="submit">Create source</button>
    </form></section>
    """


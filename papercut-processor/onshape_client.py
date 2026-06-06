"""OnShape client with two interchangeable auth backends.

Auth selection (first match wins):
  1. API key  — ONSHAPE_ACCESS_KEY + ONSHAPE_SECRET_KEY are both set.
  2. Session  — ONSHAPE_USERNAME + ONSHAPE_PASSWORD are both set.

To force session auth when API keys are also present, unset ONSHAPE_ACCESS_KEY.
"""

import os
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def parse_onshape_url(url: str) -> tuple[str, str, str, str]:
    """Parse OnShape URL to extract did, wvm, wvmid, eid."""
    pattern = r"https://cad\.onshape\.com/documents/([a-f0-9]+)/(w|v|m)/([a-f0-9]+)/e/([a-f0-9]+)"
    match = re.match(pattern, url)
    if not match:
        raise ValueError(f"Invalid OnShape URL: {url}")
    return match.groups()


# ---------------------------------------------------------------------------
# Base client — all API logic; subclasses provide _get / _post
# ---------------------------------------------------------------------------

class _OnShapeClient:
    BASE_URL = "https://cad.onshape.com/api"

    # -- transport (override in subclasses) ----------------------------------

    def _get(self, path: str, **kwargs) -> requests.Response:
        raise NotImplementedError

    def _post(self, path: str, **kwargs) -> requests.Response:
        raise NotImplementedError

    # -- helpers -------------------------------------------------------------

    def _checked_get(self, path: str, label: str, **kwargs) -> dict:
        r = self._get(path, **kwargs)
        if r.status_code != 200:
            raise ValueError(f"Failed to {label}: {r.status_code} - {r.text}")
        return r.json()

    def _checked_post(self, path: str, label: str, **kwargs) -> dict:
        r = self._post(path, **kwargs)
        if r.status_code != 200:
            raise ValueError(f"Failed to {label}: {r.status_code} - {r.text}")
        return r.json()

    # -- public API ----------------------------------------------------------

    def download_from_onshape(self, url: str, output_path: str) -> None:
        """Download a STEP export of an assembly or part studio."""
        did, wvm, wvmid, eid = parse_onshape_url(url)

        # 1. Determine element type
        elements_data = self._checked_get(
            f"documents/d/{did}/{wvm}/{wvmid}/elements",
            "get elements",
        )
        elements = elements_data if isinstance(elements_data, list) else elements_data.get("elements", [])
        element_type = next((e.get("elementType") for e in elements if e.get("id") == eid), None)
        if not element_type:
            raise ValueError(f"Element {eid} not found in document.")

        if element_type == "PARTSTUDIO":
            type_path = "partstudios"
        elif element_type == "ASSEMBLY":
            type_path = "assemblies"
        else:
            raise ValueError(f"Unsupported element type: {element_type}")

        # 2. Initiate translation
        print(f"Initiating STEP translation ({type_path}) ...")
        translation_data = self._checked_post(
            f"{type_path}/d/{did}/{wvm}/{wvmid}/e/{eid}/translations",
            "initiate translation",
            json={"formatName": "STEP", "storeInDocument": False, "allowFaultyParts": True},
        )
        translation_id = translation_data.get("id")

        # 3. Poll for completion
        print(f"Polling translation {translation_id} ...")
        while True:
            poll_data = self._checked_get(f"translations/{translation_id}", "poll translation")
            state = poll_data.get("requestState")
            if state == "DONE":
                result_ids = poll_data.get("resultExternalDataIds")
                if not result_ids:
                    raise ValueError("No resultExternalDataIds in completed translation.")
                external_data_id = result_ids[0]
                break
            elif state == "FAILED":
                raise ValueError(f"Translation failed: {poll_data.get('failureReason')}")
            else:
                print(f"  state: {state} — waiting ...")
                time.sleep(5)

        # 4. Download
        print(f"Downloading external data {external_data_id} ...")
        r = self._get(f"documents/d/{did}/externaldata/{external_data_id}", stream=True)
        if r.status_code != 200:
            raise ValueError(f"Failed to download: {r.status_code} - {r.text}")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Saved to {output_path}")

    def get_part_studio_features(self, url: str) -> list:
        """Return all features for the Part Studio element."""
        did, wvm, wvmid, eid = parse_onshape_url(url)
        print(f"Fetching features ...")
        data = self._checked_get(
            f"partstudios/d/{did}/{wvm}/{wvmid}/e/{eid}/features",
            "get features",
        )
        return data.get("features", [])

    def get_sketch_plane_matrix(self, url: str, fid: str) -> str:
        """Infer a view matrix for the sketch plane from tessellated entities."""
        did, wvm, wvmid, eid = parse_onshape_url(url)

        default_matrix = "1,0,0,0,0,0,1,0,0,-1,0,0,0.12576859794099288,-0.2053552979996751,0.1563701997820698,1"
        trans = "0.12576859794099288,-0.2053552979996751,0.1563701997820698,1"

        print(f"Fetching tessellated entities for {fid} ...")
        r = self._get(f"partstudios/d/{did}/{wvm}/{wvmid}/e/{eid}/sketches/{fid}/tessellatedentities")
        if r.status_code != 200:
            print(f"  Warning: {r.status_code} — using default matrix.")
            return default_matrix

        entities = r.json().get("sketchEntities", [])
        pts = [p for ent in entities for p in ent.get("tessellationPoints", []) if len(p) == 3]

        if len(pts) < 3:
            print("  Warning: not enough points — using default matrix.")
            return default_matrix

        var_x = max(p[0] for p in pts) - min(p[0] for p in pts)
        var_y = max(p[1] for p in pts) - min(p[1] for p in pts)
        var_z = max(p[2] for p in pts) - min(p[2] for p in pts)
        print(f"  Variance X={var_x:.4f} Y={var_y:.4f} Z={var_z:.4f}")

        min_var = min(var_x, var_y, var_z)
        if min_var == var_z:
            print("  Detected Front/Back plane (X-Y).")
            return f"1,0,0,0,0,1,0,0,0,0,1,0,{trans}"
        elif min_var == var_y:
            print("  Detected Top/Bottom plane (X-Z).")
            return f"1,0,0,0,0,0,1,0,0,-1,0,0,{trans}"
        else:
            print("  Detected Side plane (Y-Z).")
            return f"0,0,1,0,0,1,0,0,-1,0,0,0,{trans}"

    def export_feature_dxf(self, url: str, feature_id: str, output_path: str) -> None:
        """Export a sketch feature as DXF via the exportinternal endpoint."""
        did, wvm, wvmid, eid = parse_onshape_url(url)
        view_matrix = self.get_sketch_plane_matrix(url, feature_id)
        payload = {
            "format": "DXF",
            "view": view_matrix,
            "destinationName": "exported_feature",
            "version": "Release 14",
            "units": "millimeter",
            "flatten": "true",
            "includeSketches": "true",
            "triggerAutoDownload": "true",
            "storeInDocument": "false",
            "featureIds": feature_id,
        }

        print(f"Exporting feature {feature_id} as DXF ...")
        r = self._post(f"documents/d/{did}/{wvm}/{wvmid}/e/{eid}/exportinternal", json=payload, stream=True)
        if r.status_code != 200:
            raise ValueError(f"Failed to export feature: {r.status_code} - {r.text}")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Saved to {output_path}")

    def export_engravings(self, url: str, output_dir: str) -> None:
        """Find the 'engravings' folder and export every sketch inside as DXF."""
        features = self.get_part_studio_features(url)
        used_names: set[str] = set()
        engravings_folder_id = None

        for feat in features:
            msg = feat.get("message", {})
            if msg.get("name") == "engravings":
                engravings_folder_id = msg.get("featureId")
                break

        if not engravings_folder_id:
            print("No 'engravings' folder found — searching for sketches with 'engrave' in name.")
            for feat in features:
                msg = feat.get("message", {})
                name = msg.get("name")
                if msg.get("featureType") == "newSketch" and name and "engrave" in name.lower():
                    fid = msg.get("featureId")
                    output_name = name.replace("_engrave", "").replace("_engraving", "")
                    if output_name in used_names:
                        raise ValueError(f"Conflicting engraving name in OnShape: {output_name}")
                    used_names.add(output_name)
                    self.export_feature_dxf(url, fid, os.path.join(output_dir, f"{output_name}.dxf"))
            return

        print(f"Found 'engravings' folder (ID: {engravings_folder_id}).")
        found_any = False
        record = False
        for feat in features:
            msg = feat.get("message", {})
            fid = msg.get("featureId")

            if fid == engravings_folder_id:
                record = True
                continue

            if record:
                if msg.get("featureType") == "folder":
                    break
                if msg.get("featureType") == "newSketch":
                    name = msg.get("name")
                    fid = msg.get("featureId")
                    if name in used_names:
                        raise ValueError(f"Conflicting engraving name in OnShape: {name}")
                    used_names.add(name)
                    self.export_feature_dxf(url, fid, os.path.join(output_dir, f"{name}.dxf"))
                    found_any = True

        if not found_any:
            print("No sketches found in 'engravings' folder.")


# ---------------------------------------------------------------------------
# API-key client
# ---------------------------------------------------------------------------

class OnShapeApiKeyClient(_OnShapeClient):
    """Authenticates via ONSHAPE_ACCESS_KEY / ONSHAPE_SECRET_KEY (HTTP Basic)."""

    def __init__(self, access_key: str, secret_key: str):
        self._auth = (access_key, secret_key)

    def _get(self, path: str, **kwargs) -> requests.Response:
        return requests.get(f"{self.BASE_URL}/{path}", auth=self._auth, **kwargs)

    def _post(self, path: str, **kwargs) -> requests.Response:
        return requests.post(f"{self.BASE_URL}/{path}", auth=self._auth, **kwargs)


# ---------------------------------------------------------------------------
# Session (username / password) client
# ---------------------------------------------------------------------------

class OnShapeSessionClient(_OnShapeClient):
    """Authenticates via ONSHAPE_USERNAME / ONSHAPE_PASSWORD (browser session)."""

    def __init__(self, username: str, password: str):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US",
            "Origin": "https://cad.onshape.com",
        })
        self._login(username, password)

    def _login(self, username: str, password: str) -> None:
        base = "https://cad.onshape.com/api/v14"

        # Step 1 — fetch login metadata (establishes initial cookies)
        r = self._session.post(
            f"{base}/users/logininfo",
            json={"email": username},
            headers={"Referer": "https://cad.onshape.com/signin"},
        )
        if r.status_code != 200:
            raise ValueError(f"OnShape logininfo failed: {r.status_code} - {r.text}")

        # Step 2 — authenticate and receive session cookies
        r = self._session.post(
            f"{base}/users/session",
            json={"email": username, "password": password, "webClientCapabilities": {}},
            headers={"Referer": f"https://cad.onshape.com/signin?page=2&email={username}"},
        )
        if r.status_code != 200:
            raise ValueError(f"OnShape login failed: {r.status_code} - {r.text}")

        self._refresh_xsrf()
        user_name = r.json().get("name", username)
        print(f"OnShape session auth: logged in as {user_name!r}")

    def _refresh_xsrf(self) -> None:
        xsrf = self._session.cookies.get("XSRF-TOKEN")
        if xsrf:
            self._session.headers["X-XSRF-TOKEN"] = xsrf

    def _get(self, path: str, **kwargs) -> requests.Response:
        return self._session.get(f"{self.BASE_URL}/{path}", **kwargs)

    def _post(self, path: str, **kwargs) -> requests.Response:
        self._refresh_xsrf()
        return self._session.post(f"{self.BASE_URL}/{path}", **kwargs)


# ---------------------------------------------------------------------------
# Client factory and module-level helpers
# ---------------------------------------------------------------------------

_client: _OnShapeClient | None = None


def _get_client() -> _OnShapeClient:
    """Return a cached client, auto-selecting the auth backend from env vars.

    API-key auth takes precedence; session auth is used as the fallback so that
    existing configurations keep working without any changes.
    """
    global _client
    if _client is not None:
        return _client

    access_key = os.environ.get("ONSHAPE_ACCESS_KEY")
    secret_key = os.environ.get("ONSHAPE_SECRET_KEY")
    username = os.environ.get("ONSHAPE_USERNAME")
    password = os.environ.get("ONSHAPE_PASSWORD")

    if access_key and secret_key:
        _client = OnShapeApiKeyClient(access_key, secret_key)
    elif username and password:
        _client = OnShapeSessionClient(username, password)
    else:
        raise ValueError(
            "No OnShape credentials found. Set ONSHAPE_ACCESS_KEY + ONSHAPE_SECRET_KEY "
            "or ONSHAPE_USERNAME + ONSHAPE_PASSWORD."
        )
    return _client


# Module-level functions — unchanged public API consumed by __main__.py

def download_from_onshape(url: str, output_path: str) -> None:
    _get_client().download_from_onshape(url, output_path)


def get_part_studio_features(url: str) -> list:
    return _get_client().get_part_studio_features(url)


def export_feature_dxf(url: str, feature_id: str, output_path: str) -> None:
    _get_client().export_feature_dxf(url, feature_id, output_path)


def export_engravings(url: str, output_dir: str) -> None:
    _get_client().export_engravings(url, output_dir)

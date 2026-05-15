import os
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv()

def parse_onshape_url(url: str) -> tuple[str, str, str, str]:
    """Parse OnShape URL to extract did, wvm, wvmid, eid."""
    pattern = r"https://cad\.onshape\.com/documents/([a-f0-9]+)/(w|v|m)/([a-f0-9]+)/e/([a-f0-9]+)"
    match = re.match(pattern, url)
    if not match:
        raise ValueError(f"Invalid OnShape URL: {url}")
    return match.groups()

def get_onshape_credentials() -> tuple[str, str]:
    """Get OnShape credentials from environment variables."""
    access_key = os.environ.get("ONSHAPE_ACCESS_KEY")
    secret_key = os.environ.get("ONSHAPE_SECRET_KEY")
    if not access_key or not secret_key:
        raise ValueError(
            "OnShape API keys not found in environment. "
            "Please set ONSHAPE_ACCESS_KEY and ONSHAPE_SECRET_KEY."
        )
    return access_key, secret_key

def download_from_onshape(url: str, output_path: str):
    """Download STEP file from OnShape URL."""
    did, wvm, wvmid, eid = parse_onshape_url(url)
    access_key, secret_key = get_onshape_credentials()
    
    base_url = "https://cad.onshape.com/api"
    auth = (access_key, secret_key)
    
    # 1. Get element info to find type
    elements_url = f"{base_url}/documents/d/{did}/{wvm}/{wvmid}/elements"
    print(f"Fetching elements from {elements_url} ...")
    response = requests.get(elements_url, auth=auth)
    if response.status_code != 200:
        raise ValueError(f"Failed to get elements: {response.status_code} - {response.text}")
    
    elements_data = response.json()
    elements = elements_data if isinstance(elements_data, list) else elements_data.get("elements", [])
    
    element_type = None
    for el in elements:
        if el.get("id") == eid:
            element_type = el.get("elementType")
            break
            
    if not element_type:
        raise ValueError(f"Element {eid} not found in document.")
        
    if element_type == "PARTSTUDIO":
        type_path = "partstudios"
    elif element_type == "ASSEMBLY":
        type_path = "assemblies"
    else:
        raise ValueError(f"Unsupported element type: {element_type}")

        
    # 2. Initiate translation
    translate_url = f"{base_url}/{type_path}/d/{did}/{wvm}/{wvmid}/e/{eid}/translations"
    body = {
        "formatName": "STEP",
        "storeInDocument": False,
        "allowFaultyParts": True
    }
    
    print(f"Initiating translation at {translate_url} ...")
    response = requests.post(translate_url, auth=auth, json=body)
    if response.status_code != 200:
        raise ValueError(f"Failed to initiate translation: {response.status_code} - {response.text}")
        
    translation_data = response.json()
    translation_id = translation_data.get("id")
    
    # 3. Poll for completion
    poll_url = f"{base_url}/translations/{translation_id}"
    print(f"Polling translation status from {poll_url} ...")
    
    while True:
        response = requests.get(poll_url, auth=auth)
        if response.status_code != 200:
            raise ValueError(f"Failed to poll translation: {response.status_code} - {response.text}")
            
        poll_data = response.json()
        state = poll_data.get("requestState")
        
        if state == "DONE":
            print("Translation complete.")
            result_ids = poll_data.get("resultExternalDataIds")
            if not result_ids:
                raise ValueError("No resultExternalDataIds found in completed translation.")
            external_data_id = result_ids[0]
            break
        elif state == "FAILED":
            raise ValueError(f"Translation failed: {poll_data.get('failureReason')}")
        else:
            print(f"Translation state: {state}. Waiting...")
            time.sleep(5)
            
    # 4. Download file
    download_url = f"{base_url}/documents/d/{did}/externaldata/{external_data_id}"
    print(f"Downloading file from {download_url} ...")
    
    response = requests.get(download_url, auth=auth, stream=True)
    if response.status_code != 200:
        raise ValueError(f"Failed to download file: {response.status_code} - {response.text}")
        
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            
    print(f"Saved to {output_path}")

def get_part_studio_features(url: str) -> list:
    """List features in the Part Studio."""
    did, wvm, wvmid, eid = parse_onshape_url(url)
    access_key, secret_key = get_onshape_credentials()
    
    base_url = "https://cad.onshape.com/api"
    auth = (access_key, secret_key)
    
    features_url = f"{base_url}/partstudios/d/{did}/{wvm}/{wvmid}/e/{eid}/features"
    print(f"Fetching features from {features_url} ...")
    response = requests.get(features_url, auth=auth)
    if response.status_code != 200:
        raise ValueError(f"Failed to get features: {response.status_code} - {response.text}")
        
    data = response.json()
    return data.get("features", [])

def get_sketch_plane_matrix(url: str, fid: str) -> str:
    """Fetch tessellated entities and determine the view matrix based on the plane."""
    did, wvm, wvmid, eid = parse_onshape_url(url)
    access_key, secret_key = get_onshape_credentials()
    auth = (access_key, secret_key)
    
    tess_url = f"https://cad.onshape.com/api/partstudios/d/{did}/{wvm}/{wvmid}/e/{eid}/sketches/{fid}/tessellatedentities"
    print(f"Fetching tessellated entities for {fid} ...")
    response = requests.get(tess_url, auth=auth)
    
    # Default matrix (Top view from the curl)
    default_matrix = "1,0,0,0,0,0,1,0,0,-1,0,0,0.12576859794099288,-0.2053552979996751,0.1563701997820698,1"
    
    if response.status_code != 200:
        print(f"Warning: Failed to get tessellated entities: {response.status_code}. Using default matrix.")
        return default_matrix
        
    data = response.json()
    entities = data.get("sketchEntities", [])
    
    if not entities:
        print("Warning: No sketch entities found. Using default matrix.")
        return default_matrix
        
    # Collect points
    pts = []
    for ent in entities:
        tess_pts = ent.get("tessellationPoints", [])
        for p in tess_pts:
            if len(p) == 3:
                pts.append(p)
                
    if len(pts) < 3:
        print("Warning: Not enough points to determine plane. Using default matrix.")
        return default_matrix
        
    # Find variance in X, Y, Z
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    
    var_x = max(xs) - min(xs)
    var_y = max(ys) - min(ys)
    var_z = max(zs) - min(zs)
    
    print(f"Variance - X: {var_x:.4f}, Y: {var_y:.4f}, Z: {var_z:.4f}")
    
    # Heuristic: the plane with the smallest variance is the normal plane
    min_var = min(var_x, var_y, var_z)
    
    # Translation part from the curl (keep it consistent)
    trans = "0.12576859794099288,-0.2053552979996751,0.1563701997820698,1"
    
    if min_var == var_z:
        print("Detected Front/Back plane (X-Y).")
        # Front view: Identity rotation
        return f"1,0,0,0,0,1,0,0,0,0,1,0,{trans}"
    elif min_var == var_y:
        print("Detected Top/Bottom plane (X-Z).")
        # Top view (from curl)
        return f"1,0,0,0,0,0,1,0,0,-1,0,0,{trans}"
    else:
        print("Detected Side plane (Y-Z).")
        # Side view: Look down X
        return f"0,0,1,0,0,1,0,0,-1,0,0,0,{trans}"

def export_feature_dxf(url: str, feature_id: str, output_path: str):
    """Export a specific feature as DXF using the exportinternal endpoint."""
    did, wvm, wvmid, eid = parse_onshape_url(url)
    access_key, secret_key = get_onshape_credentials()
    
    base_url = "https://cad.onshape.com/api"
    auth = (access_key, secret_key)
    
    export_url = f"{base_url}/documents/d/{did}/{wvm}/{wvmid}/e/{eid}/exportinternal"
    
    # Get matrix dynamically
    view_matrix = get_sketch_plane_matrix(url, feature_id)
    
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
        "featureIds": feature_id
    }


    
    print(f"Exporting feature {feature_id} to {export_url} ...")
    response = requests.post(export_url, auth=auth, json=payload, stream=True)
    if response.status_code != 200:
        raise ValueError(f"Failed to export feature: {response.status_code} - {response.text}")
        
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            
    print(f"Saved to {output_path}")

def export_engravings(url: str, output_dir: str):
    """Search for 'engravings' directory and export sketches inside it."""
    features = get_part_studio_features(url)
    
    engravings_folder_id = None
    
    # Look for a feature named 'engravings' in the message field
    for feat in features:
        message = feat.get("message", {})
        if message.get("name") == "engravings":
            engravings_folder_id = message.get("featureId")
            break
            
    used_names = set()
            
    if not engravings_folder_id:
        print("No 'engravings' folder found. Searching for sketches with 'engrave' in name.")
        for feat in features:
            message = feat.get("message", {})
            name = message.get("name")
            ftype = message.get("featureType")
            
            if ftype == "newSketch" and name and "engrave" in name.lower():
                fid = message.get("featureId")
                
                # Strip _engrave or _engraving from filename for matching with part names
                output_name = name.replace("_engrave", "").replace("_engraving", "")
                
                # Fail fast on conflicting names
                if output_name in used_names:
                    raise ValueError(f"Conflicting engraving name found in OnShape: {output_name}")
                used_names.add(output_name)
                
                output_path = os.path.join(output_dir, f"{output_name}.dxf")
                export_feature_dxf(url, fid, output_path)
        return
        
    print(f"Found 'engravings' folder (ID: {engravings_folder_id}).")



    
    found_any = False
    record = False
    for feat in features:
        message = feat.get("message", {})
        fid = message.get("featureId")
        
        if fid == engravings_folder_id:
            record = True
            continue
            
        if record:
            # Stop at next folder
            if message.get("featureType") == "folder":
                break
                
            if message.get("featureType") == "newSketch":
                name = message.get("name")
                fid = message.get("featureId")
                
                # Fail fast on conflicting names
                if name in used_names:
                    raise ValueError(f"Conflicting engraving name found in OnShape: {name}")
                used_names.add(name)
                
                output_path = os.path.join(output_dir, f"{name}.dxf")
                export_feature_dxf(url, fid, output_path)
                found_any = True
                
    if not found_any:
        print("No sketches found in 'engravings' folder.")



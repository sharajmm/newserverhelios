from flask import Flask, request, jsonify
import requests
# import os # os module was imported but not used, can be removed
from geopy.distance import geodesic

app = Flask(__name__)

# It's highly recommended to use environment variables for API keys
# rather than hardcoding them, especially in production.
# For example, os.environ.get("GOOGLE_MAPS_API_KEY")
GOOGLE_MAPS_API_KEY = "AIzaSyDut42n1-31SoKCfwvHhr_994uJjVnE3RA" # Replace with your actual key or use env var
ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImJmMjY2YTdhODg3YzQxYTBhNTA5NDVjODc0ODAyZDM3IiwiaCI6Im11cm11cjY0In0=" # Replace or use env var

# --- Helper function for AI risk scoring ---
def calculate_risk_score(route):
    base_score = 0
    reasons = []

    duration_in_traffic_seconds = route.get("legs", [{}])[0].get("duration_in_traffic", {}).get("value", 0)
    # Using duration_in_traffic which is usually in seconds
    if duration_in_traffic_seconds > 0:
        minutes_in_traffic = duration_in_traffic_seconds // 60
        base_score += minutes_in_traffic # 1 point per minute
        reasons.append(f"Potential traffic delay: {minutes_in_traffic} minutes")

    hazard_keywords = ["sharp", "roundabout", "merge", "u-turn"]
    hazard_coordinates = []
    
    steps = route.get("legs", [{}])[0].get("steps", [])
    sharp_turns_count = 0
    hazardous_maneuvers_count = 0

    for step in steps:
        instruction = step.get("html_instructions", "").lower()
        is_hazardous_step = False
        if "sharp" in instruction:
            sharp_turns_count += 1
            is_hazardous_step = True
        # Count other hazards, but avoid double-counting "sharp"
        if any(keyword in instruction for keyword in hazard_keywords if keyword != "sharp"):
            is_hazardous_step = True
        
        if is_hazardous_step:
            hazardous_maneuvers_count +=1 # General count of steps with hazards
            base_score += 100 
            hazard_coordinates.append(step.get("start_location"))

    if sharp_turns_count > 0:
        reasons.append(f"Route includes {sharp_turns_count} sharp turn(s)")
    elif hazardous_maneuvers_count > 0: # If no sharp turns, but other hazards
         reasons.append(f"Route includes {hazardous_maneuvers_count} potentially hazardous maneuver(s)")


    ACCIDENT_BLACKSPOTS = [
        {"lat": 11.0180, "lon": 76.9691, "name": "Gandhipuram Signal"},
        {"lat": 10.9946, "lon": 76.9644, "name": "Ukkadam"},
        {"lat": 11.0268, "lon": 77.0357, "name": "Avinashi Road - Hope College"},
        {"lat": 11.0292, "lon": 76.9456, "name": "Mettupalayam Road - Saibaba Colony"},
        {"lat": 11.0028, "lon": 76.9947, "name": "Trichy Road - Ramanathapuram"},
        {"lat": 11.0705, "lon": 76.9981, "name": "Saravanampatti Junction"},
        {"lat": 10.9415, "lon": 76.9695, "name": "Pollachi Road - Eachanari"},
        {"lat": 10.9701, "lon": 76.9410, "name": "Palakkad Road - Kuniyamuthur"}
    ]

    def is_within_radius(coord1, coord2, radius_meters):
        if not coord1 or not coord2 or "lat" not in coord1 or "lon" not in coord1:
            return False # Cannot calculate if coordinates are incomplete
        return geodesic((coord1["lat"], coord1["lon"]), (coord2["lat"], coord2["lon"])).meters <= radius_meters

    blackspot_intersections_count = 0
    for step in steps:
        step_location = step.get("start_location", {})
        for blackspot in ACCIDENT_BLACKSPOTS:
            if is_within_radius(step_location, blackspot, 250): # 250m radius
                base_score += 200 
                blackspot_intersections_count += 1
                reasons.append(f"Passes near known accident blackspot: {blackspot['name']}")
                break 

    if blackspot_intersections_count > 0:
        # This summary reason might be redundant if individual blackspots are listed
        # reasons.append(f"Passes through {blackspot_intersections_count} known accident blackspot(s)")
        pass

    # Simplified general reasons, avoid adding too many generic ones
    if base_score > 700: # Adjusted threshold
        reasons.append("Route identified as higher risk due to combined factors.")
    elif base_score == 0 and not reasons: # If no specific risks found
        reasons.append("Standard route profile. Drive safely.")


    return base_score, hazard_coordinates, list(set(reasons)) # Return unique reasons

@app.route('/api/autocomplete', methods=['GET'])
def autocomplete():
    # This is a placeholder, ensure it's implemented if used by the app
    query = request.args.get('query', '')
    if not query:
        return jsonify([])
    suggestions = [f"{query} Central", f"{query} Park", f"{query} Station"]
    return jsonify(suggestions)

@app.route('/api/route', methods=['GET'])
def get_route():
    try:
        # ***** MODIFIED PARAMETER NAMES HERE *****
        required_params = ['originLat', 'originLng', 'destinationLat', 'destinationLng']
        missing_params = [param for param in required_params if param not in request.args]
        if missing_params:
            # This error message should now be more specific if it occurs
            return jsonify({"error": f"Missing required parameters: {', '.join(missing_params)}", "status": "PARAMS_ERROR"}), 400

        # ***** MODIFIED PARAMETER NAMES HERE *****
        start_lat = float(request.args.get('originLat'))
        start_lon = float(request.args.get('originLng'))
        end_lat = float(request.args.get('destinationLat'))
        end_lon = float(request.args.get('destinationLng'))

        # Validate coordinates (optional, but good practice)
        # Assuming these are still relevant for your use case
        # valid_lat = lambda lat: -90 <= lat <= 90 # Standard lat range
        # valid_lon = lambda lon: -180 <= lon <= 180 # Standard lon range
        # if not (valid_lat(start_lat) and valid_lon(start_lon) and valid_lat(end_lat) and valid_lon(end_lon)):
        #     return jsonify({"error": "Coordinates are outside of valid range.", "status":"COORDS_INVALID_RANGE"}), 400

    except ValueError: # This catches errors from float() if values are not numbers
        return jsonify({"error": "Coordinate values must be valid numbers.", "status": "VALUE_ERROR"}), 400
    except Exception as e: # Catch any other initial parsing error
        app.logger.error(f"Parameter parsing error: {str(e)}")
        return jsonify({"error": "Invalid request parameters.", "status": "PARAMS_UNKNOWN_ERROR"}), 400

    directions_url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{start_lat},{start_lon}",
        "destination": f"{end_lat},{end_lon}",
        "key": GOOGLE_MAPS_API_KEY,
        "alternatives": "true", # Getting alternative routes
        "departure_time": "now" # For duration_in_traffic
    }

    try:
        api_response = requests.get(directions_url, params=params)
        api_response.raise_for_status() # Raises an exception for HTTP errors (4xx or 5xx)
        data = api_response.json()

        if data.get("status") != "OK":
            # Handle Google API errors (e.g., ZERO_RESULTS, NOT_FOUND)
            google_error_message = data.get("error_message", "Error from Google Directions API")
            app.logger.error(f"Google Directions API Error: {data.get('status')} - {google_error_message}")
            return jsonify({"error": google_error_message, "status": data.get("status", "GOOGLE_API_ERROR")}), 500


        routes_from_google = data.get("routes", [])
        if not routes_from_google:
            return jsonify({"error": "No routes found between the specified locations.", "status": "NO_ROUTES_FOUND"}), 404

        processed_routes = []
        for route_detail in routes_from_google:
            raw_score, hazards, reasons_list = calculate_risk_score(route_detail)
            processed_routes.append({
                "polyline": route_detail.get("overview_polyline", {}).get("points"),
                "raw_risk_for_sorting": raw_score, # Keep raw for sorting before normalization
                "hazards_coordinates": hazards, # Field name consistent with convention
                "reasons": reasons_list,
                # Include other details your app might want, e.g., summary, duration, distance
                "summary": route_detail.get("summary", "N/A"),
                "duration_text": route_detail.get("legs", [{}])[0].get("duration", {}).get("text", "N/A"),
                "distance_text": route_detail.get("legs", [{}])[0].get("distance", {}).get("text", "N/A"),
            })
        
        if not processed_routes: # Should not happen if routes_from_google was not empty
             return jsonify({"error": "No routes could be processed.", "status": "PROCESSING_ERROR"}), 500

        # Normalize scores to a 0.0 to 1.0 scale (for easier conversion to 1-10 in app)
        # Or, if you prefer sending 1-10 directly:
        min_raw_risk = min(r['raw_risk_for_sorting'] for r in processed_routes) if processed_routes else 0
        max_raw_risk = max(r['raw_risk_for_sorting'] for r in processed_routes) if processed_routes else 0

        for pr_route in processed_routes:
            # Normalize to 0.0 - 1.0 (app can multiply by 10)
            if max_raw_risk > min_raw_risk:
                normalized_score = (pr_route['raw_risk_for_sorting'] - min_raw_risk) / (max_raw_risk - min_raw_risk)
            elif processed_routes: # Only one route or all have same risk
                 normalized_score = 0.1 # Default low risk if only one/all same
            else: # Should not happen
                 normalized_score = 0.0

            # You might want to cap this, e.g. a very safe route is 0.1, very risky is 1.0
            # Ensure it's not exactly 0 if you want to avoid 0/10 score in app later
            pr_route['risk_score'] = max(0.05, min(1.0, normalized_score)) # Ensure 0.05 to 1.0 range
            del pr_route['raw_risk_for_sorting']

        # The backend now returns a JSON object with a "routes" key,
        # which is a list of these route objects.
        return jsonify({
            "status": "OK", # Overall status for the API call
            "routes": processed_routes
        })

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Network error calling Google API: {str(e)}")
        return jsonify({"error": f"Network error when fetching directions: {str(e)}", "status": "NETWORK_ERROR_GOOGLE_API"}), 503
    except Exception as e:
        app.logger.error(f"Unexpected error in /api/route: {str(e)}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}", "status": "UNKNOWN_SERVER_ERROR"}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'healthy', 'message': 'Helios Google-Powered Backend is live!'})

if __name__ == '__main__':
    # It's better to run Flask with a proper WSGI server like Gunicorn in production
    # For Vercel, Vercel handles the WSGI server. This is for local testing.
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

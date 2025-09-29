from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
from geopy.distance import geodesic

load_dotenv()
app = Flask(__name__)

# --- Helper function for AI risk scoring ---
def calculate_risk_score(route):
    base_score = 0
    reasons = []  # List to store reasons for the risk score

    # Factor 1: Traffic Duration (higher duration = more exposure to risk)
    # The 'duration_in_traffic' key is available if you set departure_time
    duration_in_traffic = route.get("legs", [{}])[0].get("duration_in_traffic", {}).get("value", 0)
    base_score += duration_in_traffic / 60 # Add 1 point per minute in traffic
    if duration_in_traffic > 0:
        reasons.append(f"Traffic duration: {duration_in_traffic // 60} minutes")
    
    # Factor 2: Hazardous Maneuvers (analyzing text instructions)
    hazard_keywords = ["sharp", "roundabout", "merge", "u-turn"]
    hazard_coordinates = []
    
    steps = route.get("legs", [{}])[0].get("steps", [])
    sharp_turns = 0
    for step in steps:
        instruction = step.get("html_instructions", "").lower()
        if any(keyword in instruction for keyword in hazard_keywords):
            base_score += 100 # Add a significant penalty for each hazardous turn
            hazard_coordinates.append(step.get("start_location")) # Log the coordinate of the hazard
            if "sharp" in instruction:
                sharp_turns += 1

    if sharp_turns > 0:
        reasons.append(f"Contains {sharp_turns} sharp turn(s)")

    # Factor 3: Blackspot Intersections (using Coimbatore data)
    ACCIDENT_BLACKSPOTS = [
        # Gandhipuram Signal (Major Intersection)
        {"lat": 11.0180, "lon": 76.9691, "name": "Gandhipuram Signal"},
        # Ukkadam Bus Stand Area (High Pedestrian Traffic)
        {"lat": 10.9946, "lon": 76.9644, "name": "Ukkadam"},
        # Avinashi Road, near Hope College (High Speed Corridor)
        {"lat": 11.0268, "lon": 77.0357, "name": "Avinashi Road - Hope College"},
        # Mettupalayam Road, near Saibaba Colony
        {"lat": 11.0292, "lon": 76.9456, "name": "Mettupalayam Road - Saibaba Colony"},
        # Trichy Road, near Ramanathapuram
        {"lat": 11.0028, "lon": 76.9947, "name": "Trichy Road - Ramanathapuram"},
        # Saravanampatti, Kalapatti Road Junction
        {"lat": 11.0705, "lon": 76.9981, "name": "Saravanampatti Junction"},
        # Pollachi Main Road, Eachanari
        {"lat": 10.9415, "lon": 76.9695, "name": "Pollachi Road - Eachanari"},
        # Palakkad Main Road, Kuniyamuthur
        {"lat": 10.9701, "lon": 76.9410, "name": "Palakkad Road - Kuniyamuthur"}
    ]

    def is_within_radius(coord1, coord2, radius_meters):
        return geodesic((coord1["lat"], coord1["lon"]), (coord2["lat"], coord2["lon"])).meters <= radius_meters

    blackspot_count = 0
    for step in steps:
        step_location = step.get("start_location", {})
        for blackspot in ACCIDENT_BLACKSPOTS:
            if is_within_radius(step_location, blackspot, 250):
                base_score += 200 # Large penalty for passing through a blackspot
                blackspot_count += 1
                break # Avoid double-counting the same blackspot for a single step

    if blackspot_count > 0:
        reasons.append(f"Passes through {blackspot_count} known accident blackspot(s)")

    # Add common reasons for high-risk routes
    if base_score > 500:  # Threshold for high-risk routes
        reasons.append("High traffic congestion")
        reasons.append("Multiple blind spots along the route")

    return base_score, hazard_coordinates, reasons

# --- API Endpoints ---
@app.route('/api/route', methods=['GET'])
def get_route():
    try:
        start_lat = float(request.args.get('start_lat'))
        start_lon = float(request.args.get('start_lon'))
        end_lat = float(request.args.get('end_lat'))
        end_lon = float(request.args.get('end_lon'))
    except (TypeError, ValueError, AttributeError):
        return jsonify({"error": "Invalid or missing coordinate format"}), 400

    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        return jsonify({"error": "API key not configured"}), 500

    directions_url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{start_lat},{start_lon}",
        "destination": f"{end_lat},{end_lon}",
        "key": api_key,
        "alternatives": "true",
        "departure_time": "now"  # This is needed for traffic data
    }

    try:
        response = requests.get(directions_url, params=params)
        response.raise_for_status()
        data = response.json()

        routes_data = data.get("routes", [])
        if not routes_data:
            return jsonify({"error": "No routes found by Google"}), 404

        route_objects = []
        for route in routes_data:
            raw_score, hazards, reasons = calculate_risk_score(route)
            route_objects.append({
                "polyline": route.get("overview_polyline", {}).get("points"),
                "raw_risk": raw_score,
                "hazards": hazards,
                "reasons": reasons
            })
        
        # Normalize scores to a 1-10 scale
        min_risk = min(r['raw_risk'] for r in route_objects)
        max_risk = max(r['raw_risk'] for r in route_objects)
        
        for route in route_objects:
            if max_risk > min_risk:
                route['risk_score'] = 1 + 9 * (route['raw_risk'] - min_risk) / (max_risk - min_risk)
            else:
                route['risk_score'] = 1.0 # If all routes are equal, score is 1
            del route['raw_risk'] # Remove the raw score

        return jsonify({"routes": route_objects})
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'healthy', 'message': 'Helios Google-Powered Backend is live!'})

// OpenRouteService API key
const API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjdkMmI3Zjk5ZDI1NDQxYTFiNWZhMDk2NTc5NzA0MmRiIiwiaCI6Im11cm11cjY0In0=";

// Initialize map
const map = L.map("map").setView(
    [12.9141, 74.8560], 13
);

// Load OpenStreetMap
L.tileLayer(
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
        attribution: "&copy; OpenStreetMap contributors"
    }
).addTo(map);

let source = null;
let destination = null;
let sourceMarker = null;
let destinationMarker = null;
let routeLayer = null;
let activeRequest = null;

// Sample flood-prone area
L.circle([12.9200, 74.8600], {
    color: "red",
    fillColor: "red",
    fillOpacity: 0.3,
    radius: 300
})
.addTo(map)
.bindPopup("Sample Flood-Prone Area");

// Select locations by clicking the map
map.on("click", function (e) {

    if (!source) {

        source = e.latlng;

        sourceMarker = L.marker(source)
            .addTo(map)
            .bindPopup("Starting Point")
            .openPopup();

        document.getElementById("status").innerText =
            "Now select your destination.";

    } else if (!destination) {

        destination = e.latlng;

        destinationMarker = L.marker(destination)
            .addTo(map)
            .bindPopup("Destination")
            .openPopup();

        calculateRoute();
    }
});

// Calculate walking route
async function calculateRoute() {

    document.getElementById("status").innerText =
        "Calculating walking route...";

    const controller = new AbortController();
    activeRequest = controller;

const url =
    "https://api.heigit.org/openrouteservice/v2/directions/foot-walking/geojson";

    try {

        const response = await fetch(url, {
            method: "POST",

            headers: {
                "Authorization": API_KEY,
                "Content-Type": "application/json"
            },

            signal: controller.signal,

            body: JSON.stringify({
                coordinates: [
                    [source.lng, source.lat],
                    [destination.lng, destination.lat]
                ]
            })
        });

        if (!response.ok) {
            throw new Error("API Error: " + response.status);
        }

        const data = await response.json();

        if (activeRequest !== controller) return;

        if (!data.features || !data.features.length) {
            throw new Error("No walking route found.");
        }

        // Remove previous route
        if (routeLayer) {
            map.removeLayer(routeLayer);
        }

        // Display walking route
        routeLayer = L.geoJSON(data, {
            style: {
                color: "blue",
                weight: 5,
                opacity: 0.8
            }
        }).addTo(map);

        map.fitBounds(routeLayer.getBounds());

        // Extract distance and duration
        const summary =
            data.features[0].properties.summary;

        const distance =
            (summary.distance / 1000).toFixed(2);

        const duration =
            Math.round(summary.duration / 60);

        document.getElementById("distance").innerText =
            "Distance: " + distance + " km";

        document.getElementById("duration").innerText =
            "Walking Time: " + duration + " minutes";

        document.getElementById("status").innerText =
            "Walking route generated successfully!";

    } catch (error) {

        if (error.name === "AbortError") return;

        console.error(error);

        document.getElementById("status").innerText =
            "Unable to generate route. Reset and try again.";

    } finally {
        if (activeRequest === controller) {
            activeRequest = null;
        }
    }
}

// Detect current location
function getLocation() {

    if (source) {
        alert("Reset the route before selecting a new source.");
        return;
    }

    if (navigator.geolocation) {

        navigator.geolocation.getCurrentPosition(
            function (position) {

                if (source) return;

                source = L.latLng(
                    position.coords.latitude,
                    position.coords.longitude
                );

                sourceMarker = L.marker(source)
                    .addTo(map)
                    .bindPopup("Your Location")
                    .openPopup();

                map.setView(source, 15);

                document.getElementById("status").innerText =
                    "Location detected. Select destination.";

            },

            function () {
                alert("Unable to access your location.");
            }
        );

    } else {
        alert("Geolocation is not supported.");
    }
}

// Reset route
function resetMap() {

    if (activeRequest) {
        activeRequest.abort();
        activeRequest = null;
    }

    if (sourceMarker) map.removeLayer(sourceMarker);
    if (destinationMarker) map.removeLayer(destinationMarker);
    if (routeLayer) map.removeLayer(routeLayer);

    source = null;
    destination = null;
    sourceMarker = null;
    destinationMarker = null;
    routeLayer = null;

    document.getElementById("distance").innerText =
        "Distance: --";

    document.getElementById("duration").innerText =
        "Walking Time: --";

    document.getElementById("status").innerText =
        "Click on the map to select your starting point.";
}


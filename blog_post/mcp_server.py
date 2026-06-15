from fastmcp import FastMCP

mcp = FastMCP(name="RestaurantReviewsMCP")

# Static sample values keep the MCP auth example focused on identity.
# Replace these lists with database queries or API calls when you need dynamic data.
RESTAURANTS = [
    {
        "id": 1,
        "name": "Contoso Curry House",
        "cuisine": "Indian",
        "street_address": "12 Market Street",
        "description": "A casual spot for thali, biryani, and late-night chai.",
        "avg_rating": 4.7,
        "review_count": 128,
    },
    {
        "id": 2,
        "name": "Northwind Noodles",
        "cuisine": "Japanese",
        "street_address": "48 Harbor Road",
        "description": "Small ramen bar known for rich broth and quick service.",
        "avg_rating": 4.5,
        "review_count": 94,
    },
    {
        "id": 3,
        "name": "Fabrikam Fire Grill",
        "cuisine": "Modern Australian",
        "street_address": "7 King Avenue",
        "description": "Open-flame cooking with seasonal local produce.",
        "avg_rating": 4.2,
        "review_count": 61,
    },
]

REVIEWS = {
    1: [
        {"user_name": "Maya", "rating": 5, "review_text": "Great spice balance and fast service."},
        {"user_name": "Liam", "rating": 4, "review_text": "Loved the biryani. The dining room was busy."},
    ],
    2: [
        {"user_name": "Noah", "rating": 5, "review_text": "Excellent broth and perfectly cooked noodles."},
        {"user_name": "Ava", "rating": 4, "review_text": "Compact menu, but everything tasted fresh."},
    ],
    3: [
        {"user_name": "Amelia", "rating": 4, "review_text": "The grill flavors were excellent."},
        {"user_name": "Ethan", "rating": 4, "review_text": "Good option for a team dinner."},
    ],
}


@mcp.tool()
async def list_restaurants_mcp() -> list[dict]:
    """List restaurants with their average rating and review count."""

    return RESTAURANTS


@mcp.tool()
async def get_details_mcp(restaurant_id: int) -> dict | None:
    """Return a restaurant and its sample reviews."""

    restaurant = next(
        (item for item in RESTAURANTS if item["id"] == restaurant_id),
        None,
    )
    if restaurant is None:
        return None

    return {
        "restaurant": restaurant,
        "reviews": REVIEWS.get(restaurant_id, []),
    }


@mcp.tool()
async def recommend_restaurant_mcp(
    cuisine: str | None = None,
    minimum_rating: float = 4.0,
) -> dict:
    """Recommend the highest-rated restaurant that matches the filters."""

    matches = [
        restaurant
        for restaurant in RESTAURANTS
        if restaurant["avg_rating"] >= minimum_rating
        and (cuisine is None or restaurant["cuisine"].lower() == cuisine.lower())
    ]
    if not matches:
        return {
            "recommendation": None,
            "reason": "No restaurant matched the requested filters.",
        }

    recommendation = max(matches, key=lambda item: item["avg_rating"])
    return {
        "recommendation": recommendation,
        "reason": f"Highest-rated match at {recommendation['avg_rating']} stars.",
    }


@mcp.tool()
async def summarize_restaurant_mcp(restaurant_id: int) -> dict | None:
    """Create a short agent-friendly restaurant summary."""

    details = await get_details_mcp(restaurant_id)
    if details is None:
        return None

    restaurant = details["restaurant"]
    summary = (
        f"{restaurant['name']} is a {restaurant['cuisine']} restaurant rated "
        f"{restaurant['avg_rating']} stars across {restaurant['review_count']} reviews. "
        f"It is located at {restaurant['street_address']}."
    )
    return {
        "restaurant_id": restaurant_id,
        "summary": summary,
    }

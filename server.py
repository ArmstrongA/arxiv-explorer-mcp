import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

import boto3
from fastmcp import FastMCP
from tavily import TavilyClient
from dotenv import load_dotenv

# Only load .env file if it exists (for local development)
if os.path.exists('.env'):
    load_dotenv()
    print("✅ Loaded .env file for local development")
else:
    print("✅ No .env file found - using environment variables from runtime")

# --- Configuration ---
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
if not TAVILY_API_KEY:
    raise ValueError("Please set the TAVILY_API_KEY environment variable.")

# DynamoDB Configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")  # Only set for local development

# Check DynamoDB endpoint configuration
if DYNAMODB_ENDPOINT:
    print(f"🔧 Using DynamoDB Local endpoint: {DYNAMODB_ENDPOINT}")
else:
    print("🔧 Using AWS DynamoDB service (production mode)")

# Initialize clients
tavily = TavilyClient(api_key=TAVILY_API_KEY)
mcp = FastMCP(name="ArxivExplorer")

# Initialize DynamoDB with conditional endpoint
dynamodb_config = {
    'region_name': AWS_REGION,
    'aws_access_key_id': os.environ.get("AWS_ACCESS_KEY_ID"),
    'aws_secret_access_key': os.environ.get("AWS_SECRET_ACCESS_KEY")
}

# Only add endpoint_url if DYNAMODB_ENDPOINT is set (for local development)
if DYNAMODB_ENDPOINT:
    dynamodb_config['endpoint_url'] = DYNAMODB_ENDPOINT

# --- Database Setup ---
# def setup_database():
#     """Create DynamoDB tables if they don't exist."""
#     try:
#         # Papers table for storing search results
#         papers_table = dynamodb.create_table(
#             TableName='papers',
#             KeySchema=[
#                 {'AttributeName': 'url', 'KeyType': 'HASH'}  # Primary key
#             ],
#             AttributeDefinitions=[
#                 {'AttributeName': 'url', 'AttributeType': 'S'}
#             ],
#             BillingMode='PAY_PER_REQUEST'
#         )
#         papers_table.wait_until_exists()
#         print("✅ Created 'papers' table")
#     except dynamodb.meta.client.exceptions.ResourceInUseException:
#         print("✅ 'papers' table already exists")
    
#     try:
#         # Searches table for storing search history
#         searches_table = dynamodb.create_table(
#             TableName='searches',
#             KeySchema=[
#                 {'AttributeName': 'search_id', 'KeyType': 'HASH'}
#             ],
#             AttributeDefinitions=[
#                 {'AttributeName': 'search_id', 'AttributeType': 'S'}
#             ],
#             BillingMode='PAY_PER_REQUEST'
#         )
#         searches_table.wait_until_exists()
#         print("✅ Created 'searches' table")
#     except dynamodb.meta.client.exceptions.ResourceInUseException:
#         print("✅ 'searches' table already exists")

# # Setup database on startup
# setup_database()

dynamodb = boto3.resource('dynamodb', **dynamodb_config)

print("✅ ArxivExplorer server initialized with DynamoDB.")

# Get table references
papers_table = dynamodb.Table('papers')
searches_table = dynamodb.Table('searches')

# --- Helper Functions ---
def save_paper(title: str, url: str, summary: str = None):
    """Save paper to database."""
    papers_table.put_item(
        Item={
            'url': url,
            'title': title,
            'summary': summary,
            'timestamp': datetime.now().isoformat()
        }
    )

def get_paper(url: str) -> Optional[Dict]:
    """Get paper from database."""
    try:
        response = papers_table.get_item(Key={'url': url})
        return response.get('Item')
    except Exception:
        return None

def save_search(query: str, results: List[Dict]):
    """Save search results to database."""
    search_id = f"{query}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    searches_table.put_item(
        Item={
            'search_id': search_id,
            'query': query,
            'results': results,
            'timestamp': datetime.now().isoformat()
        }
    )
    return search_id

# --- Dynamic Resource: Suggested AI research topics ---
@mcp.resource("resource://ai/arxiv_topics")
def arxiv_topics() -> List[str]:
    return [
        "Transformer interpretability",
        "Efficient large-scale model training",
        "Federated learning privacy",
        "Neural network pruning",
        "Multi-modal AI systems",
        "AI safety and alignment"
    ]

# --- Enhanced Tool: Search ArXiv with caching ---
@mcp.tool(annotations={"title": "Search Arxiv"})
def search_arxiv(query: str, max_results: int = 5) -> List[Dict]:
    """
    Queries ArXiv via Tavily, returning title + link for each paper.
    Results are cached in DynamoDB for future reference.
    """
    print(f"🔍 Searching ArXiv for: {query}")
    
    resp = tavily.search(
        query=f"site:arxiv.org {query}",
        max_results=max_results
    )
    
    results = []
    for r in resp.get("results", []):
        paper_data = {
            "title": r["title"].strip(), 
            "url": r["url"]
        }
        results.append(paper_data)
        
        # Save to database
        save_paper(paper_data["title"], paper_data["url"])
    
    # Save search history
    search_id = save_search(query, results)
    print(f"✅ Search saved with ID: {search_id}")
    
    return results

# --- Enhanced Tool: Summarize with caching ---
@mcp.tool(annotations={"title": "Summarize Paper"})
def summarize_paper(paper_url: str) -> str:
    """
    Returns a summary of the paper. Checks cache first, then generates new summary.
    """
    print(f"📝 Summarizing paper: {paper_url}")
    
    # Check if we already have a summary
    cached_paper = get_paper(paper_url)
    if cached_paper and cached_paper.get('summary'):
        print("✅ Using cached summary")
        return cached_paper['summary']
    
    # Generate new summary
    prompt = f"Summarize the key contributions of this ArXiv paper: {paper_url}"
    summary = tavily.qna_search(query=prompt)
    
    # Update the paper record with summary
    if cached_paper:
        papers_table.update_item(
            Key={'url': paper_url},
            UpdateExpression='SET summary = :summary',
            ExpressionAttributeValues={':summary': summary}
        )
    else:
        # Create new record if paper doesn't exist
        save_paper("Unknown Title", paper_url, summary)
    
    print("✅ Summary generated and cached")
    return summary

# --- New Tool: Get Search History ---
@mcp.tool(annotations={"title": "Get Search History"})
def get_search_history(limit: int = 10) -> List[Dict]:
    """
    Returns recent search history from the database.
    """
    try:
        response = searches_table.scan(Limit=limit)
        items = response.get('Items', [])
        
        # Sort by timestamp (most recent first)
        sorted_items = sorted(items, key=lambda x: x['timestamp'], reverse=True)
        
        return [{
            'search_id': item['search_id'],
            'query': item['query'],
            'timestamp': item['timestamp'],
            'result_count': len(item.get('results', []))
        } for item in sorted_items]
    except Exception as e:
        print(f"❌ Error fetching search history: {e}")
        return []

# --- New Tool: Get Saved Papers ---
@mcp.tool(annotations={"title": "Get Saved Papers"})
def get_saved_papers(limit: int = 20) -> List[Dict]:
    """
    Returns saved papers from the database.
    """
    try:
        response = papers_table.scan(Limit=limit)
        items = response.get('Items', [])
        
        return [{
            'title': item['title'],
            'url': item['url'],
            'has_summary': bool(item.get('summary')),
            'timestamp': item['timestamp']
        } for item in items]
    except Exception as e:
        print(f"❌ Error fetching saved papers: {e}")
        return []

print("✅ All tools registered with DynamoDB integration.")

# --- Prompt Template ---
@mcp.prompt
def explore_topic_prompt(topic: str) -> str:
    return (
        f"I want to explore recent work on '{topic}'.\n"
        f"1. Call 'Search Arxiv' to find the 5 most recent papers.\n"
        f"2. For each paper URL, call 'Summarize Paper' to extract key contributions.\n"
        f"3. Use 'Get Search History' to see if we've explored similar topics.\n"
        f"4. Combine all information into a comprehensive overview report."
    )

print("✅ Prompt 'explore_topic_prompt' registered.")

if __name__ == "__main__":
    print("\n🚀 Starting ArxivExplorer Server with DynamoDB...")
    mcp.run(transport="http", host="0.0.0.0", port=8080)
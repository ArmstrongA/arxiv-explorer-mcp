import ast
import asyncio
import pprint

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

# --- Configuration ---
SERVER_URL = "http://localhost:8080/mcp"  # Updated port for our enhanced server

pp = pprint.PrettyPrinter(indent=2, width=100)

def unwrap_tool_result(resp):
    """
    Safely unwraps the content from a FastMCP tool call result object.
    """
    if hasattr(resp, "content") and resp.content:
        content_object = resp.content[0]
        
        if hasattr(content_object, "text"):
            try:
                import json
                result = json.loads(content_object.text)
                return result
            except json.JSONDecodeError:
                try:
                    result = ast.literal_eval(content_object.text)
                    return result
                except (ValueError, SyntaxError):
                    return content_object.text
        
        if hasattr(content_object, "json") and callable(content_object.json):
            return content_object.json()
    
    return resp

async def main():
    transport = StreamableHttpTransport(url=SERVER_URL)
    client = Client(transport)

    print("\n🚀 Connecting to Enhanced ArxivExplorer server at:", SERVER_URL)
    async with client:
        # 1. Test connectivity
        print("\n🔗 Testing server connectivity...")
        await client.ping()
        print("✅ Server is reachable!\n")

        # 2. Discover capabilities
        print("🛠️  Available tools:")
        tools = await client.list_tools()
        pp.pprint(tools)
        
        print("\n📚 Available resources:")
        pp.pprint(await client.list_resources())

        # 3. Test the enhanced search with database
        print("\n\n🔍 Testing enhanced search_arxiv with database...")
        raw_search = await client.call_tool(
            "search_arxiv",
            {"query": "Large Language Models", "max_results": 3},
        )
        
        search_results = unwrap_tool_result(raw_search)
        print(f"✅ Found and cached {len(search_results)} papers")
        
        for i, paper in enumerate(search_results, 1):
            print(f"  {i}. {paper['title']}\n     {paper['url']}")

        # 4. Test summarization with caching
        if search_results and len(search_results) > 0:
            first_paper = search_results[0]
            print(f"\n📝 Testing summarize_paper with caching...")
            
            # First call - will generate and cache
            raw_summary = await client.call_tool(
                "summarize_paper", {"paper_url": first_paper["url"]}
            )
            summary = unwrap_tool_result(raw_summary)
            print(f"Summary (first call): {summary[:200]}...")
            
            # Second call - should use cache
            print("\n🔄 Testing cached summary retrieval...")
            raw_summary2 = await client.call_tool(
                "summarize_paper", {"paper_url": first_paper["url"]}
            )
            summary2 = unwrap_tool_result(raw_summary2)
            print(f"Summary (cached): {summary2[:200]}...")

        # 5. Test new database tools
        print("\n\n📚 Testing get_saved_papers...")
        raw_papers = await client.call_tool("get_saved_papers", {"limit": 5})
        saved_papers = unwrap_tool_result(raw_papers)
        print(f"✅ Retrieved {len(saved_papers)} saved papers:")
        for paper in saved_papers:
            print(f"  - {paper['title']} (Summary: {'Yes' if paper['has_summary'] else 'No'})")

        print("\n📈 Testing get_search_history...")
        raw_history = await client.call_tool("get_search_history", {"limit": 5})
        search_history = unwrap_tool_result(raw_history)
        print(f"✅ Retrieved {len(search_history)} search records:")
        for search in search_history:
            print(f"  - '{search['query']}' ({search['result_count']} results) at {search['timestamp']}")

        # 6. Test the prompt
        print("\n\n🚀 Testing enhanced explore_topic_prompt...")
        prompt_resp = await client.get_prompt(
            "explore_topic_prompt", {"topic": "AI Safety"}
        )
        print("Generated exploration prompt:")
        for msg in prompt_resp.messages:
            print(f"{msg.role.upper()}: {msg.content.text}\n")

        print("✅ All tests completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
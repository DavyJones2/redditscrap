from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import praw
from langdetect import detect, LangDetectException
import re
import openai
import asyncio
import os

# Environment variables for credentials
client_id = os.environ.get('client_id')
client_secret = os.environ.get('client_secret')
openAI = os.environ.get('openAI')

# Configure Reddit API credentials
reddit = praw.Reddit(
    client_id=client_id,
    client_secret=client_secret,
    user_agent='your_user_agent'
)

subreddit = reddit.subreddit("all")

# OpenAI API key configuration
openai.api_key = openAI

# Define the FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connections list to handle multiple clients
active_connections = []

# Utility functions
def is_link(text):
    url_pattern = re.compile(
        r'^(https?://)?'
        r'([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}'
        r'(/[a-zA-Z0-9#-]+)*'
        r'(\?[a-zA-Z0-9=&]+)?'
        r'/?$'
    )
    return bool(url_pattern.match(text))

def truncate_text_to_token_limit(text, max_tokens=4000):
    max_characters = max_tokens * 4
    return text[:max_characters] if len(text) > max_characters else text

async def extract(keywords, dataNum):
    """Extract posts from Reddit based on keywords and dataNum."""
    local_posts = []
    for keyword in keywords:
        for submission in subreddit.search(keyword, sort="new", limit=dataNum):
            try:
                language = detect(submission.title + " " + submission.selftext)
                body = submission.selftext.strip()  # Clean body text

                # Apply filters
                if (
                    language == 'en' and
                    body and
                    not is_link(body) and
                    len(body.split()) >= 20
                ):
                    truncated_body = truncate_text_to_token_limit(body)
                    post_info = [submission.title, submission.url, truncated_body]
                    local_posts.append(post_info)
            except LangDetectException:
                print("Could not detect language for this post. Skipping...")
    return local_posts

async def general(user_input, posts):
    """Process posts with GPT and filter relevant ones."""
    local_list1 = []
    batch_size = 5
    delay = 15
    retry_attempts = 3

    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        for post in batch:
            title, url, truncated_body = post
            system_message = f"""
            Post text: {truncated_body}

            You are an AI assistant that evaluates text content. Your task is to determine if the given text discusses 
            any aspect of AI that might be dangerous or have a negative impact on humanity in the future.
            Respond with only "Yes" if the content is potentially dangerous or harmful, otherwise respond with "No".
            """
            attempt = 0
            while attempt < retry_attempts:
                try:
                    response = await openai.ChatCompletion.acreate(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": system_message},
                            {"role": "user", "content": user_input}
                        ]
                    )
                    if response['choices'][0]['message']['content'] == "Yes":
                        local_list1.append(post)
                    break
                except openai.error.RateLimitError:
                    attempt += 1
                    print(f"Rate limit exceeded, attempt {attempt}. Waiting before retrying...")
                    await asyncio.sleep(delay * (2 ** attempt))

        # Add delay to prevent hitting rate limits
        await asyncio.sleep(10)
    return local_list1

# WebSocket endpoint for real-time updates
@app.websocket("/ws/chatbot")
async def websocket_chatbot(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    active_connections.append(websocket)

    try:
        await websocket.send_text("WebSocket connection established.")
        while True:
            # Receive JSON data from WebSocket
            data = await websocket.receive_json()
            keywords = data.get("keywords", [])
            data_num = data.get("data_num", 10)

            await websocket.send_text(f"Extracting posts for keywords: {keywords}")
            posts = await extract(keywords, data_num)

            await websocket.send_text(f"{len(posts)} posts extracted. Processing started.")
            filtered_posts = await general("Please classify the post correctly", posts)

            await websocket.send_text(f"Processing completed. {len(filtered_posts)} posts matched the criteria.")
            response_links = [post[1] for post in filtered_posts]
            await websocket.send_json({"response": response_links})

            await websocket.send_text("Processing complete. Send new data to process.")
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        print("WebSocket disconnected.")
    except Exception as e:
        await websocket.send_text(f"An error occurred: {str(e)}")
        raise

# Run the FastAPI app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", port=8000, reload=True)

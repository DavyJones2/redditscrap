from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import praw
from langdetect import detect, LangDetectException
import re
import openai
import time
import os
import asyncio

client_id = os.environ.get('client_id')
client_secret = os.environ.get('client_secret')
openAI = os.environ.get('openAI')

# Configure Reddit API credentials
reddit = praw.Reddit(
    client_id=(client_id),
    client_secret=(client_secret),
    user_agent='your_user_agent'
)

subreddit = reddit.subreddit("all")

# OpenAI API key configuration
openai.api_key = (openAI)

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


def extract(keywords, dataNum):
    posts = []
    print(f"received: {dataNum}")
    for keyword in keywords:
        for submission in subreddit.search(keyword, sort="new", limit=dataNum):
            try:
                # Detect language from the title or body
                language = detect(submission.title + " " + submission.selftext)
                body = submission.selftext.strip()  # Get the body and remove extra whitespace
                
                # Apply filters: language, non-empty body, not a link, and minimum word count
                if (
                    language == 'en' and           # English language
                    body and                       # Non-empty body
                    not is_link(body) and          # Body is not just a link
                    len(body.split()) >= 20        # Body has at least 20 words
                ):
                    # Truncate the body text if it exceeds GPT-4 token limit
                    truncated_body = truncate_text_to_token_limit(body)
                    
                    post_info = [
                        submission.title,    # Title
                        submission.url,      # URL
                        truncated_body       # Truncated Body
                    ]
                    posts.append(post_info)
            except LangDetectException:
                print("Could not detect language for this post. Skipping...")
    return posts

# Request and Response Models
class ChatRequest(BaseModel):
    keywords: list
    data_num: int

async def general_stream(user_input, posts):
    n = 0
    batch_size = 5  # Define the batch size to control the number of requests per batch
    delay = 20       # Initial delay in seconds after a rate limit error
    retry_attempts = 3  # Maximum retry attempts for each post

    try:
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
                n += 1
                print(f"Processing post {n}")

                attempt = 0
                while attempt < retry_attempts:
                    try:
                        response = openai.ChatCompletion.create(
                            model="gpt-4",
                            messages=[
                                {"role": "system", "content": system_message},
                                {"role": "user", "content": user_input}
                            ]
                        )
                        is_dangerous = response['choices'][0]['message']['content'] == "Yes"
                        if is_dangerous:
                            print(f"data: url: {url}\n")
                            yield f"data: url: {url}\n"
                        else:
                            print(url)
                        break  # Exit the retry loop if the request is successful

                    except openai.error.RateLimitError:
                        attempt += 1
                        print(f"Rate limit exceeded, attempt {attempt}. Waiting before retrying...")
                        await asyncio.sleep(delay * (2 ** attempt))  # Exponential backoff

            # After each batch, add a delay to avoid rate limiting
            print("Batch completed, waiting before next batch...")
            await asyncio.sleep(20)  # Modify this as needed based on your rate limits

    except Exception as e:
        yield f"data: Error: {str(e)}\n\n"


 # Define the API endpoint
@app.post("/chatbot")
async def chatbot_response(request: ChatRequest):
    keywords = request.keywords
    print(keywords)
    data_num = request.data_num
    print(f"Data: {data_num}")
    v = extract(keywords, data_num)
    print(len(v))
    return StreamingResponse(
        general_stream("Please classify the post correctly", v),
        media_type="text/event-stream"
    )






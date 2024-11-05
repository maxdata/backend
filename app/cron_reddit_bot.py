import praw
import orjson
from datetime import datetime
import os
from dotenv import load_dotenv
import time


def format_time(time_str):
    """Format time string to AM/PM format"""
    if not time_str:
        return ""
    
    try:
        time_parts = time_str.split(':')
        hours = int(time_parts[0])
        minutes = int(time_parts[1])
        
        period = "AM" if hours < 12 else "PM"
        if hours > 12:
            hours -= 12
        elif hours == 0:
            hours = 12
            
        return f"{hours:02d}:{minutes:02d} {period}"
    except:
        return ""


def format_number(num):
    """Abbreviate large numbers with B/M suffix"""
    if num >= 1_000_000_000:
        return f"${num / 1_000_000_000:.2f}B"
    elif num >= 1_000_000:
        return f"${num / 1_000_000:.2f}M"
    return f"${num:,.0f}"

def calculate_yoy_change(current, prior):
    """Calculate year-over-year percentage change"""
    if prior and prior != 0:
        return ((current / prior - 1) * 100)
    return 0

def get_market_timing(time_str):
    """Determine if earnings are before, after, or during market hours"""
    if not time_str:
        return ""
    
    try:
        time_parts = time_str.split(':')
        hours = int(time_parts[0])
        minutes = int(time_parts[1])
        
        if hours < 9 or (hours == 9 and minutes <= 30):
            return "before market opens."
        elif hours >= 16:
            return "after market closes."
        else:
            return "during market."
    except:
        return ""

def format_upcoming_earnings_data(earnings_data):
    """Format earnings data into Reddit-friendly markdown with hyperlinks."""
    formatted_items = []
    
    for item in earnings_data:
        symbol = item.get('symbol', None)
        if symbol is not None:
            name = item.get('name', 'Unknown')
            market_timing = get_market_timing(item.get('time'))
            revenue_formatted = format_number(item.get('revenueEst', 0))
            revenue_yoy = calculate_yoy_change(item.get('revenueEst', 0), item.get('revenuePrior', 1))  # Avoid division by zero
            eps_yoy = calculate_yoy_change(item.get('epsEst', 0), item.get('epsPrior', 1))  # Avoid division by zero

            # Determine reporting time text
            if item.get('isToday'):
                report_timing = "will report today"
            else:
                current_day = datetime.now().strftime('%A')
                report_timing = "will report tomorrow" if current_day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday'] else "will report Monday"
            
            # Create hyperlink for symbol
            symbol_link = f"[{symbol}](https://stocknear.com/stocks/{symbol})"

            # Format the entry text
            entry = (
                f"* **{name}** ({symbol_link}) {report_timing} {market_timing} "
                f"Analysts estimate {revenue_formatted} in revenue ({revenue_yoy:.2f}% YoY) and "
                f"${item.get('epsEst', 0):.2f} in earnings per share ({eps_yoy:.2f}% YoY).\n\n"
            )
            formatted_items.append(entry)
    
    return "".join(formatted_items)

def format_recent_earnings_data(earnings_data):
    """Format earnings data into Reddit-friendly markdown with bullet points."""
    formatted_items = []
    
    for item in earnings_data:
        symbol = item.get('symbol', None)
        if symbol is not None:
            name = item.get('name', 'Unknown')
            time = format_time(item.get('time', ''))
            
            # Financial calculations
            revenue = item.get('revenue', 0)  # Changed from revenueEst to revenue for actual results
            revenue_prior = item.get('revenuePrior', 1)
            revenue_surprise = item.get('revenueSurprise', 0)
            eps = item.get('eps', 0)  # Changed from epsEst to eps for actual results
            eps_prior = item.get('epsPrior', 1)
            eps_surprise = item.get('epsSurprise', 0)
            
            # Calculate YoY changes
            revenue_yoy = calculate_yoy_change(revenue, revenue_prior)
            eps_yoy = calculate_yoy_change(eps, eps_prior)
            
            # Format numbers
            revenue_formatted = format_number(revenue)
            revenue_surprise_formatted = format_number(abs(revenue_surprise))
            
            # Determine growth/decline text
            revenue_trend = "growth" if revenue_yoy >= 0 else "decline"
            eps_trend = "growth" if eps_yoy >= 0 else "decline"
            
            # Create hyperlink for symbol
            symbol_link = f"[{symbol}](https://stocknear.com/stocks/{symbol})"
            
            # Format the entry text with nested bullet points
            entry = (
                f"**{name}** ({symbol_link}) has released its quarterly earnings at {time}:\n\n"
                f"* Revenue of {revenue_formatted} "
                f"{'exceeds' if revenue_surprise > 0 else 'misses'} estimates by {revenue_surprise_formatted}, "
                f"with {revenue_yoy:.2f}% YoY {revenue_trend}.\n\n"
                f"* EPS of ${eps:.2f} "
                f"{'exceeds' if eps_surprise > 0 else 'misses'} estimates by ${abs(eps_surprise):.2f}, "
                f"with {eps_yoy:.2f}% YoY {eps_trend}.\n\n"
            )

            formatted_items.append(entry)
    
    return "".join(formatted_items)

def post_to_reddit():
    # Load environment variables
    load_dotenv()
    
    # Get current date
    today = datetime.now()
    month_str = today.strftime("%b")
    day = today.day
    year = today.year  # Added the year variable
    day_suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    formatted_date = f"{month_str} {day}{day_suffix} {year}"
    
    # Load and format data
    with open("json/dashboard/data.json", "rb") as file:
        data = orjson.loads(file.read())
    
    #formatted_text = format_upcoming_earnings_data(data.get('upcomingEarnings', []))
    #title = f"Upcoming Earnings for today, {formatted_date}"

    formatted_text = format_recent_earnings_data(data.get('recentEarnings', []))
    title = f"Recent Earnings for today, {formatted_date}"

    try:
        # Initialize Reddit instance
        reddit = praw.Reddit(
            client_id=os.getenv('REDDIT_BOT_API_KEY'),
            client_secret=os.getenv('REDDIT_BOT_API_SECRET'),
            username=os.getenv('REDDIT_USERNAME'),
            password=os.getenv('REDDIT_PASSWORD'),
            user_agent=os.getenv('REDDIT_USER_AGENT', 'script:my_bot:v1.0 (by /u/username)')
        )
        
        # Define the subreddit and post details
        subreddit = reddit.subreddit("stocknear")
        earnings_flair_id = 'b9f76638-772e-11ef-96c1-0afbf26bd890'
        
        # Submit the post with the formatted text
        
        post = subreddit.submit(
            title=title,
            selftext=formatted_text,
            flair_id=earnings_flair_id
        )
        print(f"Post created successfully with 'Earnings' flair: {post.url}")
        

    except praw.exceptions.PRAWException as e:
        print(f"Error posting to Reddit: {str(e)}")
        return None
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return None

if __name__ == "__main__":
    post_to_reddit()
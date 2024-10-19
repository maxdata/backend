import ujson
import asyncio
import aiohttp
import sqlite3
from tqdm import tqdm
from dotenv import load_dotenv
import os
import time

load_dotenv()
api_key = os.getenv('FMP_API_KEY')


async def filter_and_deduplicate(data, excluded_domains=None, deduplicate_key='title'):
    """
    Filter out items with specified domains in their URL and remove duplicates based on a specified key.
    """
    if excluded_domains is None:
        excluded_domains = ['prnewswire.com', 'globenewswire.com', 'accesswire.com']

    seen_keys = set()
    filtered_data = []

    for item in data:
        if not any(domain in item['url'] for domain in excluded_domains):
            key = item.get(deduplicate_key)
            if key and key not in seen_keys:
                filtered_data.append(item)
                seen_keys.add(key)

    return filtered_data


async def save_json(symbol, data):
    """
    Save data as JSON in a batch to reduce disk I/O
    """
    async with asyncio.Lock():  # Ensure thread-safe writes
        with open(f"json/market-news/companies/{symbol}.json", 'w') as file:
            ujson.dump(data, file)


async def get_data(session, chunk):
    """
    Fetch data for a chunk of tickers using a single session
    """
    company_tickers = ','.join(chunk)
    url = f'https://financialmodelingprep.com/api/v3/stock_news?tickers={company_tickers}&page=0&limit=2000&apikey={api_key}'
    
    async with session.get(url) as response:
        if response.status == 200:
            return await response.json()
        return []


def get_symbols(db_name, table_name):
    """
    Fetch symbols from the SQLite database
    """
    with sqlite3.connect(db_name) as con:
        cursor = con.cursor()
        cursor.execute("PRAGMA journal_mode = wal")
        cursor.execute(f"SELECT DISTINCT symbol FROM {table_name} WHERE symbol NOT LIKE '%.%'")
        return [row[0] for row in cursor.fetchall()]


async def process_chunk(session, chunk):
    """
    Process a chunk of symbols
    """
    data = await get_data(session, chunk)
    tasks = []
    for symbol in chunk:
        filtered_data = [item for item in data if item['symbol'] == symbol]
        filtered_data = await filter_and_deduplicate(filtered_data)
        if filtered_data:
            tasks.append(save_json(symbol, filtered_data))
    if tasks:
        await asyncio.gather(*tasks)


async def main():
    """
    Main function to coordinate fetching and processing
    """
    stock_symbols = get_symbols('stocks.db', 'stocks')
    etf_symbols = get_symbols('etf.db', 'etfs')
    crypto_symbols = get_symbols('crypto.db', 'cryptos')
    total_symbols = stock_symbols + etf_symbols + crypto_symbols

    # Dynamically adjust chunk size
    chunk_size = 15  # Adjust based on your needs
    chunks = [total_symbols[i:i + chunk_size] for i in range(0, len(total_symbols), chunk_size)]

    async with aiohttp.ClientSession() as session:
        tasks = [process_chunk(session, chunk) for chunk in chunks]
        for task in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
            await task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"An error occurred: {e}")

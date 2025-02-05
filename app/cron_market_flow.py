import os
import pandas as pd
import orjson
from dotenv import load_dotenv
import sqlite3
from datetime import datetime, timedelta
from GetStartEndDate import GetStartEndDate
import asyncio
import aiohttp
import pytz
import requests  # Add missing import
from collections import defaultdict
from GetStartEndDate import GetStartEndDate
from tqdm import tqdm

import re


load_dotenv()
fmp_api_key = os.getenv('FMP_API_KEY')


ny_tz = pytz.timezone('America/New_York')

today,_ =  GetStartEndDate().run()
today = today.strftime("%Y-%m-%d")


def save_json(data):
    directory = "json/market-flow"
    os.makedirs(directory, exist_ok=True)  # Ensure the directory exists
    with open(f"{directory}/data.json", 'wb') as file:  # Use binary mode for orjson
        file.write(orjson.dumps(data))


def safe_round(value):
    try:
        return round(float(value), 2)
    except (ValueError, TypeError):
        return value

# Function to convert and match timestamps
def add_close_to_data(price_list, data):
    for entry in data:
        formatted_time = entry['time']
        # Match with price_list
        for price in price_list:
            if price['date'] == formatted_time:
                entry['close'] = price['close']
                break  # Match found, no need to continue searching
    return data



async def get_stock_chart_data(ticker):
    start_date_1d, end_date_1d = GetStartEndDate().run()
    start_date = start_date_1d.strftime("%Y-%m-%d")
    end_date = end_date_1d.strftime("%Y-%m-%d")

    url = f"https://financialmodelingprep.com/api/v3/historical-chart/1min/{ticker}?from={start_date}&to={end_date}&apikey={fmp_api_key}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                data = sorted(data, key=lambda x: x['date'])
                return data
            else:
                return []



def get_market_tide(interval_5m=True):
    res_list = []

    # Track changes per interval using a defaultdict.
    delta_data = defaultdict(lambda: {
        'cumulative_net_call_premium': 0,
        'cumulative_net_put_premium': 0,
        'call_ask_vol': 0,
        'call_bid_vol': 0,
        'put_ask_vol': 0,
        'put_bid_vol': 0
    })

    # Process for each ticker (in this case only 'SPY')
    for ticker in tqdm(['SPY']):
        # Load the data from JSON.
        with open("json/options-flow/feed/data.json", "r") as file:
            data = orjson.loads(file.read())
        
        # Filter and sort data for the given ticker.
        data = [item for item in data if item['ticker'] == ticker]
        data.sort(key=lambda x: x['time'])

        # Process each item in the data
        for item in data:
            try:
                # Combine date and time from the item.
                dt = datetime.strptime(f"{item['date']} {item['time']}", "%Y-%m-%d %H:%M:%S")
                # Truncate to the start of the minute.
                dt = dt.replace(second=0, microsecond=0)
                
                # Adjust for 5-minute intervals if requested.
                if interval_5m:
                    # Round down minutes to the nearest 5-minute mark.
                    minute = dt.minute - (dt.minute % 5)
                    dt = dt.replace(minute=minute)
                
                rounded_ts = dt.strftime("%Y-%m-%d %H:%M:%S")

                # Extract metrics.
                cost = float(item.get("cost_basis", 0))
                sentiment = item.get("sentiment", "")
                put_call = item.get("put_call", "")
                vol = int(item.get("volume", 0))

                # Update premium and volume metrics.
                if put_call == "Calls":
                    if sentiment == "Bullish":
                        delta_data[rounded_ts]['cumulative_net_call_premium'] += cost
                        delta_data[rounded_ts]['call_ask_vol'] += vol
                    elif sentiment == "Bearish":
                        delta_data[rounded_ts]['cumulative_net_call_premium'] -= cost
                        delta_data[rounded_ts]['call_bid_vol'] += vol
                elif put_call == "Puts":
                    if sentiment == "Bullish":
                        delta_data[rounded_ts]['cumulative_net_put_premium'] -= cost
                        delta_data[rounded_ts]['put_ask_vol'] += vol
                    elif sentiment == "Bearish":
                        delta_data[rounded_ts]['cumulative_net_put_premium'] += cost
                        delta_data[rounded_ts]['put_bid_vol'] += vol

            except Exception as e:
                print(f"Error processing item: {e}")

        # Calculate cumulative values over time.
        sorted_ts = sorted(delta_data.keys())
        cumulative = {
            'net_call_premium': 0,
            'net_put_premium': 0,
            'call_ask': 0,
            'call_bid': 0,
            'put_ask': 0,
            'put_bid': 0
        }

        for ts in sorted_ts:
            # Update cumulative values.
            cumulative['net_call_premium'] += delta_data[ts]['cumulative_net_call_premium']
            cumulative['net_put_premium'] += delta_data[ts]['cumulative_net_put_premium']
            cumulative['call_ask'] += delta_data[ts]['call_ask_vol']
            cumulative['call_bid'] += delta_data[ts]['call_bid_vol']
            cumulative['put_ask'] += delta_data[ts]['put_ask_vol']
            cumulative['put_bid'] += delta_data[ts]['put_bid_vol']

            # Calculate derived metrics.
            call_volume = cumulative['call_ask'] + cumulative['call_bid']
            put_volume = cumulative['put_ask'] + cumulative['put_bid']
            net_volume = (cumulative['call_ask'] - cumulative['call_bid']) - (cumulative['put_ask'] - cumulative['put_bid'])

            res_list.append({
                'time': ts,
                'ticker': ticker,
                'net_call_premium': cumulative['net_call_premium'],
                'net_put_premium': cumulative['net_put_premium'],
                'call_volume': call_volume,
                'put_volume': put_volume,
                'net_volume': net_volume
            })

    # Sort the results list by time.
    res_list.sort(key=lambda x: x['time'])

    # Retrieve price list data (either via asyncio or from file as a fallback).
    price_list = asyncio.run(get_stock_chart_data('SPY'))
    if len(price_list) == 0:
        with open("json/one-day-price/SPY.json", "r") as file:
            price_list = orjson.loads(file.read())

    # Append closing prices to the data.
    data = add_close_to_data(price_list, res_list)

    # Ensure that each minute until 16:10:00 is present in the data.
    fields = ['net_call_premium', 'net_put_premium', 'call_volume', 'put_volume', 'net_volume', 'close']
    last_time = datetime.strptime(data[-1]['time'], "%Y-%m-%d %H:%M:%S")
    end_time = datetime.strptime("2025-02-05 16:10:00", "%Y-%m-%d %H:%M:%S")

    while last_time < end_time:
        last_time += timedelta(minutes=1)
        data.append({
            'time': last_time.strftime("%Y-%m-%d %H:%M:%S"),
            'ticker': ticker,
            **{field: None for field in fields}
        })

    return data

def get_top_sector_tickers():
    keep_elements = ['price', 'ticker', 'name', 'changesPercentage','netPremium','netCallPremium','netPutPremium','gexRatio','gexNetChange','ivRank']
    sector_list = [
        "Basic Materials",
        "Communication Services",
        "Consumer Cyclical",
        "Consumer Defensive",
        "Energy",
        "Financial Services",
        "Healthcare",
        "Industrials",
        "Real Estate",
        "Technology",
        "Utilities",
    ]
    headers = {
        "Accept": "application/json, text/plain",
        "Authorization": api_key
    }
    url = "https://api.unusualwhales.com/api/screener/stocks"

    res_list = {}

    for sector in sector_list:
        querystring = {
            'order': 'net_premium',
            'order_direction': 'desc',
            'sectors[]': sector
        }

        response = requests.get(url, headers=headers, params=querystring)
        data = response.json().get('data', [])

        updated_data = []
        for item in data[:10]:
            try:
                new_item = {key: safe_round(value) for key, value in item.items()}
                with open(f"json/quote/{item['ticker']}.json") as file:
                    quote_data = orjson.loads(file.read())
                    new_item['name'] = quote_data['name']
                    new_item['price'] = round(float(quote_data['price']), 2)
                    new_item['changesPercentage'] = round(float(quote_data['changesPercentage']), 2)
                    
                    new_item['ivRank'] = round(float(new_item['iv_rank']),2)
                    new_item['gexRatio'] = new_item['gex_ratio']
                    new_item['gexNetChange'] = new_item['gex_net_change']
                    new_item['netCallPremium'] = new_item['net_call_premium']
                    new_item['netPutPremium'] = new_item['net_put_premium']

                    new_item['netPremium'] = abs(new_item['netCallPremium'] - new_item['netPutPremium'])
                # Filter new_item to keep only specified elements
                filtered_item = {key: new_item[key] for key in keep_elements if key in new_item}
                updated_data.append(filtered_item)
            except Exception as e:
                print(f"Error processing ticker {item.get('ticker', 'unknown')}: {e}")

        # Add rank to each item
        for rank, item in enumerate(updated_data, 1):
            item['rank'] = rank
        res_list[sector] = updated_data

    return res_list


def get_top_spy_tickers():
    with open(f"json/stocks-list/sp500_constituent.json", "r") as file:
        data = orjson.loads(file.read())

    res_list = []
    for item in data:
        try:
            symbol = item['symbol']
            with open(f"json/options-stats/companies/{symbol}.json","r") as file:
                stats_data = orjson.loads(file.read())
            
            new_item = {key: safe_round(value) for key, value in stats_data.items()}
            
            with open(f"json/quote/{symbol}.json") as file:
                quote_data = orjson.loads(file.read())
                new_item['symbol'] = symbol
                new_item['name'] = quote_data['name']
                new_item['price'] = round(float(quote_data['price']), 2)
                new_item['changesPercentage'] = round(float(quote_data['changesPercentage']), 2)
                
            if new_item['net_premium']:
                res_list.append(new_item)
        except:
            pass

    # Add rank to each item
    res_list = sorted(res_list, key=lambda item: item['net_premium'], reverse=True)

    for rank, item in enumerate(res_list, 1):
        item['rank'] = rank

    return res_list



def main():
    top_sector_tickers = {}

    market_tide = get_market_tide()
    top_spy_tickers = get_top_spy_tickers()
    top_sector_tickers['SPY'] = top_spy_tickers[:10]

    data = {'marketTide': market_tide, 'topSectorTickers': top_sector_tickers}

    if data:
        save_json(data)
    '''
    sector_data = get_sector_data()
    top_sector_tickers = get_top_sector_tickers()
    top_spy_tickers = get_top_spy_tickers()
    top_sector_tickers['SPY'] = top_spy_tickers
    data = {'sectorData': sector_data, 'topSectorTickers': top_sector_tickers, 'marketTide': market_tide}
    '''
    
    

if __name__ == '__main__':
    main()

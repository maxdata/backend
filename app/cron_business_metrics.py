from edgar import *
import ast
import ujson
from tqdm import tqdm
from datetime import datetime
from collections import defaultdict
import re


#Tell the SEC who you are
set_identity("Max Mustermann max.mustermann@indigo.com")


# Define quarter-end dates for a given year
#The last quarter Q4 result is not shown in any sec files
#But using the https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/nvda-20240128.htm 10-K you see the annual end result which can be subtracted with all Quarter results to obtain Q4 (dumb af but works so don't judge me people)

def format_name(name):
    # Step 1: Insert spaces between camel case transitions (lowercase followed by uppercase)
    formatted_name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    
    # Step 2: Replace "And" with "&"
    formatted_name = formatted_name.replace("And", " & ").replace('Revenue','')
    
    return formatted_name


def add_value_growth(data):
    """
    Adds a new key 'valueGrowth' to each entry in the data list.

    Parameters:
    - data (list): A list of dictionaries containing date and value lists.

    Returns:
    - list: A new list with the 'valueGrowth' key added to each dictionary.
    """
    # Initialize a new list for the output data
    updated_data = []

    # Loop through the data from the latest to the oldest
    for i in range(len(data)):
        try:
            current_entry = data[i].copy()  # Create a copy of the current entry
            current_values = current_entry['value']

            # Initialize the growth percentages list
            if i < len(data) - 1:  # Only compute growth if there is a next entry
                next_values = data[i + 1]['value']
                growth_percentages = []

                for j in range(len(current_values)):
                    # Convert values to integers if they are strings
                    next_value = int(next_values[j]) if isinstance(next_values[j], (int, str)) else 0
                    current_value = int(current_values[j]) if isinstance(current_values[j], (int, str)) else 0
                    
                    # Calculate growth percentage if next_value is not zero
                    if next_value != 0:
                        growth = round(((current_value - next_value) / next_value) * 100,2)
                    else:
                        growth = None  # Cannot calculate growth if next value is zero

                    growth_percentages.append(growth)

                current_entry['valueGrowth'] = growth_percentages  # Add the growth percentages
            else:
                current_entry['valueGrowth'] = [None] * len(current_values)  # No growth for the last entry

            updated_data.append(current_entry)  # Append the updated entry to the output list
        except:
            pass

    return updated_data

def sort_by_latest_date_and_highest_value(data):
    # Define a key function to convert the date string to a datetime object
    # and use the negative of the integer value for descending order
    def sort_key(item):
        date = datetime.strptime(item['date'], '%Y-%m-%d')
        value = -int(item['value'])  # Negative for descending order
        return (date, value)
    
    # Sort the list
    sorted_data = sorted(data, key=sort_key, reverse=True)
    
    return sorted_data

def aggregate_other_values(data):
    aggregated = defaultdict(int)
    result = []

    # First pass: aggregate 'Other' values and keep non-'Other' items
    for item in data:
        date = item['date']
        value = int(item['value'])
        if item['name'] == 'Other':
            aggregated[date] += value
        else:
            result.append(item)

    # Second pass: add aggregated 'Other' values
    for date, value in aggregated.items():
        result.append({'name': 'Other', 'value': int(value), 'date': date})

    return sorted(result, key=lambda x: (x['date'], x['name']))

# Define quarter-end dates for a given year
def closest_quarter_end(date_str):
    date = datetime.strptime(date_str, "%Y-%m-%d")
    year = date.year
    
    # Define quarter end dates for the current year
    q1 = datetime(year, 3, 31)
    q2 = datetime(year, 6, 30)
    q3 = datetime(year, 9, 30)
    q4 = datetime(year, 12, 31)

    # If the date is in January, return the last day of Q4 of the previous year
    if date.month == 1:
        closest = datetime(year - 1, 12, 31)  # Last quarter of the previous year
    else:
        # Adjust to next year's Q4 if the date is in the last quarter of the current year
        if date >= q4:
            closest = q4.replace(year=year + 1)  # Next year's last quarter
        else:
            # Find the closest quarter date
            closest = min([q1, q2, q3, q4], key=lambda d: abs(d - date))

    # Return the closest quarter date in 'YYYY-MM-DD' format
    return closest.strftime("%Y-%m-%d")


def compute_q4_results(dataset):
    # Group data by year and name
    yearly_data = defaultdict(lambda: defaultdict(dict))
    for item in dataset:
        date = datetime.strptime(item['date'], '%Y-%m-%d')
        year = date.year
        quarter = (date.month - 1) // 3 + 1
        yearly_data[year][item['name']][quarter] = item['value']

    # Calculate Q4 results and update dataset
    for year in sorted(yearly_data.keys(), reverse=True):
        for name, quarters in yearly_data[year].items():
            if 4 in quarters:  # This is the year-end total
                total = quarters[4]
                q1 = quarters.get(1, 0)
                q2 = quarters.get(2, 0)
                q3 = quarters.get(3, 0)
                q4_value = total - (q1 + q2 + q3)
                
                # Update the original dataset
                for item in dataset:
                    if item['name'] == name and item['date'] == f'{year}-12-31':
                        item['value'] = q4_value
                        break

    return dataset



def generate_geography_dataset(dataset):

    country_replacements = {
        "americas": "United States",
        "unitedstates": "United States",
        "videogamebrandsunitedstates": "United States",
        "greaterchina": "China",
        "country:us": "United States",
        "country:cn": "China",
        "chinaincludinghongkong": "China"
    }

    # Custom order for specific countries
    custom_order = {
        'United States': 2,
        'China': 1,
        'Other': 0
    }

    aggregated_data = {}

    for item in dataset:
        try:
            name = item.get('name', '').lower()
            date = item.get('date')
            value = int(float(item.get('value', 0)))

            year = int(date[:4])
            if year < 2019:
                continue  # Skip this item if the year is less than 2019

            # Replace country name if necessary
            country_name = country_replacements.get(name, 'Other')

            # Use (country_name, date) as the key to sum values
            key = (country_name, date)

            if key in aggregated_data:
                aggregated_data[key] += value  # Add the value if the country-date pair exists
            else:
                aggregated_data[key] = value  # Initialize the value if new country-date pair
        except:
            pass

    # Convert the aggregated data back into the desired list format
    dataset = [{'name': country, 'date': date, 'value': total_value} for (country, date), total_value in aggregated_data.items()]

    
    dataset = aggregate_other_values(dataset)
    dataset = sorted(
        dataset,
        key=lambda item: (datetime.strptime(item['date'], '%Y-%m-%d'), custom_order.get(item['name'], 3)),
        reverse = True
    )

    #dataset = compute_q4_results(dataset)
    result = {}

    unique_names = sorted(
            list(set(item['name'] for item in dataset if item['name'] not in {'CloudServiceAgreements'})),
            key=lambda item: custom_order.get(item, 4),  # Use 4 as default for items not in custom_order
            reverse=True)

    result = {}

    # Iterate through the original data
    for item in dataset:
        # Get the date and value
        date = item['date']
        value = item['value']
        
        # Initialize the dictionary for the date if not already done
        if date not in result:
            result[date] = {'date': date, 'value': []}
        
        # Append the value to the list
        result[date]['value'].append(value)

    # Convert the result dictionary to a list
    res_list = list(result.values())

    # Print the final result
    res_list = add_value_growth(res_list)
    
    final_result = {'names': unique_names, 'history': res_list}
    return final_result

def generate_revenue_dataset(dataset):
    name_replacements = {
        "datacenter": "Data Center",
        "professionalvisualization": "Visualization",
        "oemandother": "OEM & Other",
        "automotive": "Automotive",
        "oemip": "OEM & Other",
        "gaming": "Gaming",
        "mac": "Mac",
        "iphone": "IPhone",
        "ipad": "IPad",
        "wearableshomeandaccessories": "Wearables",
        "hardwareandaccessories": "Hardware & Accessories",
        "software": "Software",
        "collectibles": "Collectibles",
        "automotivesales": "Auto",
        "automotiveleasing": "Auto Leasing",
        "energygenerationandstoragesegment": "Energy and Storage",
        "servicesandother": "Services & Other",
        "automotiveregulatorycredits": "Regulatory Credits",
        "intelligentcloud": "Intelligent Cloud",
        "productivityandbusinessprocesses": "Productivity & Business",
        "searchandnewsadvertising": "Advertising",
        "linkedincorporation": "LinkedIn",
        "morepersonalcomputing": "More Personal Computing",
        "serviceother": "Service Other",
        "governmentoperatingsegment": "Government Operating Segment",
        "internationaldevelopmentallicensedmarketsandcorporate": "License Market",
        "youtubeadvertisingrevenue": "Youtube Ads",
        "googleadvertisingrevenue": "Google Ads",
        "cloudservicesandlicensesupport": "Cloude Services & Support",
        "infrastructurecloudservicesandlicensesupport": "Infrastructure Cloud",
        "applicationscloudservicesandlicensesupport": "Application Cloud"
    }
    excluded_names = {'government','enterpriseembeddedandsemicustom','computingandgraphics','automotiveleasing ','officeproductsandcloudservices','serverproductsandcloudservices','automotiverevenues','automotive','computeandnetworking','graphics','gpu','automotivesegment','energygenerationandstoragesales','energygenerationandstorage','automotivesaleswithoutresalevalueguarantee','salesandservices','compute', 'networking', 'cloudserviceagreements', 'digital', 'allother', 'preownedvideogameproducts'}
    dataset = [item for item in dataset if item['name'].lower() not in excluded_names]

    # Find all unique names and dates
    all_dates = sorted(set(item['date'] for item in dataset))
    all_names = sorted(set(item['name'] for item in dataset))
    dataset = [revenue for revenue in dataset if revenue['name'].lower() not in excluded_names]
    # Check and fill missing combinations at the beginning
    name_date_map = defaultdict(lambda: defaultdict(lambda: None))
    for item in dataset:
        name_date_map[item['name']][item['date']] = item['value']
    
    # Ensure all names have entries for all dates
    for name in all_names:
        for date in all_dates:
            if date not in name_date_map[name]:
                dataset.append({'name': name, 'date': date, 'value': None})
    
    # Clean and process the dataset values
    processed_dataset = []
    for item in dataset:
        if item['value'] not in (None, '', 0):
            processed_dataset.append({
                'name': item['name'],
                'date': item['date'],
                'value': int(float(item['value']))
            })
        else:
            processed_dataset.append({
                'name': item['name'],
                'date': item['date'],
                'value': None
            })
        
    dataset = processed_dataset


    #If the last value of the latest date is null or 0 remove all names in the list
    dataset = sorted(dataset, key=lambda item: datetime.strptime(item['date'], '%Y-%m-%d'), reverse=True)
    remember_names = set()  # Use a set for faster membership checks

    first_date = dataset[0]['date']

    # Iterate through dataset to remember names where date matches first_date and value is None
    for item in dataset:
        if item['date'] == first_date and (item['value'] == None or item['value'] == 0):
            remember_names.add(item['name'])
            print(item['name'])

    # Use list comprehension to filter items not in remember_names
    dataset = [{**item} for item in dataset if item['name'] not in remember_names]


    dataset = [ item for item in dataset if datetime.strptime(item['date'], '%Y-%m-%d').year >= 2019]


    # Group by name and calculate total value
    name_totals = defaultdict(int)
    for item in dataset:
        name_totals[item['name']] += item['value'] if item['value'] != None else 0

    # Sort names by total value and get top 5, ensuring excluded names are not considered
    top_names = sorted(
        [(name, total) for name, total in name_totals.items() if name.lower() not in excluded_names],
        key=lambda x: x[1],
        reverse=True
    )[:5]
    top_names = [name for name, _ in top_names]

    # Filter dataset to include only top 5 names
    dataset = [item for item in dataset if item['name'] in top_names]

    # Sort the dataset
    dataset.sort(key=lambda item: (datetime.strptime(item['date'], '%Y-%m-%d'), item['value'] if item['value'] != None else 0), reverse=True)

    top_names = [name_replacements.get(name.lower(), format_name(name)) for name in top_names]
    print(top_names)

    result = {}
    for item in dataset:
        date = item['date']
        value = item['value']
        if date not in result:
            result[date] = {'date': date, 'value': []}
        result[date]['value'].append(value)



    # Convert the result dictionary to a list
    res_list = list(result.values())
    
    # Add value growth (assuming add_value_growth function exists)
    res_list = add_value_growth(res_list)
    final_result = {'names': top_names, 'history': res_list}
    return final_result




def process_filings(filings, symbol):
    revenue_sources = []
    geography_sources = []
    

    for i in range(0,17):
        try:
            filing_xbrl = filings[i].xbrl()
            facts = filing_xbrl.facts.data
            latest_rows = facts.groupby('dimensions').head(1)
            
            for index, row in latest_rows.iterrows():
                dimensions_str = row.get("dimensions", "{}")
                try:
                    dimensions_dict = ast.literal_eval(dimensions_str) if isinstance(dimensions_str, str) else dimensions_str
                except (ValueError, SyntaxError):
                    dimensions_dict = {}
                
                #print(dimensions_dict)
                
                for column_name in [
                    "srt:StatementGeographicalAxis",
                    "us-gaap:StatementBusinessSegmentsAxis",
                    "srt:ProductOrServiceAxis",
                ]:
                    product_dimension = dimensions_dict.get(column_name) if isinstance(dimensions_dict, dict) else None
                    
                    if row["namespace"] == "us-gaap" and product_dimension is not None and (
                        product_dimension.startswith(symbol.lower() + ":") or 
                        product_dimension.startswith("country" + ":") or
                        product_dimension.startswith("us-gaap"+":") or
                        product_dimension.startswith("srt"+":") or
                        product_dimension.startswith("goog"+":")
                    ):
                        replacements = {
                            "Member": "",
                            "VideoGameAccessories": "HardwareAndAccessories",
                            "NewVideoGameHardware": "HardwareAndAccessories",
                            "NewVideoGameSoftware": "Software",
                            f"{symbol.lower()}:": "",
                            "goog:": "",
                            "us-gaap:": "",
                            "srt:": "",
                            "SegmentMember": "",
                        }
                        name = product_dimension
                        for old, new in replacements.items():
                            name = name.replace(old, new)
                        
                        if symbol in ['ORCL','SAVE','BA','NFLX','LLY','MSFT','META','NVDA','AAPL','GME']:
                            column_list = ["srt:ProductOrServiceAxis"]
                        else:
                            column_list = ["srt:ProductOrServiceAxis", "us-gaap:StatementBusinessSegmentsAxis"]
                            
                        if column_name in column_list:
                            revenue_sources.append({"name": name, "value": row["value"], "date": row["end_date"]})
                        else:
                            geography_sources.append({"name": name, "value": row["value"], "date": row["end_date"]})
                            
        except Exception as e:
            print(e)
            
    return revenue_sources, geography_sources

def run(symbol):
    # First try with 10-Q filings only
    filings = Company(symbol).get_filings(form=["10-Q"]).latest(20)
    revenue_sources, geography_sources = process_filings(filings, symbol)
    
    # If no geography sources found, try with 10-K filings
    if not geography_sources:
        print(f"No geography sources found in 10-Q for {symbol}, checking 10-K filings...")
        filings_10k = Company(symbol).get_filings(form=["10-K"]).latest(20)
        _, geography_sources = process_filings(filings_10k, symbol)
    
    print(revenue_sources)
    #print(geography_sources)
    revenue_dataset = generate_revenue_dataset(revenue_sources)
    geographic_dataset = generate_geography_dataset(geography_sources)
    final_dataset = {'revenue': revenue_dataset, 'geographic': geographic_dataset}
    
    with open(f"json/business-metrics/{symbol}.json", "w") as file:
        ujson.dump(final_dataset, file)

if __name__ == "__main__":
    for symbol in ['ORCL']: #['ORCL','GOOGL','AMD','SAVE','BA','ADBE','NFLX','PLTR','MSFT','META','TSLA','NVDA','AAPL','GME']:
        run(symbol)
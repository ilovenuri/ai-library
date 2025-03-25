import requests
from bs4 import BeautifulSoup
import time
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os.path
import pickle
from datetime import datetime

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_service():
    creds = None
    # The file token.pickle stores the user's access and refresh tokens
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('sheets', 'v4', credentials=creds)
    return service

def get_existing_papers(service, spreadsheet_id, sheet_name):
    """Get existing papers from a specific sheet."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A:D'
        ).execute()
        values = result.get('values', [])
        
        if not values:
            return []
            
        # Skip header rows and get only paper data
        return values[3:]  # Skip timestamp, empty row, and header row
    except Exception as e:
        print(f"Error getting existing papers: {e}")
        return []

def get_latest_sheet(service, spreadsheet_id):
    """Get the most recent sheet name from the spreadsheet."""
    try:
        spreadsheet = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        sheets = spreadsheet.get('sheets', [])
        
        if not sheets:
            return None
            
        # Get all sheet names and find the most recent one
        sheet_names = [sheet['properties']['title'] for sheet in sheets]
        date_sheets = [name for name in sheet_names if name.isdigit() and len(name) == 6]
        
        if not date_sheets:
            return None
            
        return max(date_sheets)  # Returns the most recent date sheet
    except Exception as e:
        print(f"Error getting latest sheet: {e}")
        return None

def create_new_sheet(service, spreadsheet_id, sheet_name):
    """Create a new sheet with the given name."""
    try:
        body = {
            'requests': [{
                'addSheet': {
                    'properties': {
                        'title': sheet_name
                    }
                }
            }]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        ).execute()
        return True
    except Exception as e:
        print(f"Error creating new sheet: {e}")
        return False

def crawl_arxiv_papers():
    # URL for recent cs.AI papers
    url = "https://arxiv.org/list/cs.AI/recent"
    
    # Headers to mimic a browser request
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # Make the request
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all paper entries
        papers = []
        entries = soup.find_all('dt')
        abstracts = soup.find_all('dd')
        
        for entry, abstract in zip(entries, abstracts):
            # Extract paper ID and arXiv link
            paper_link = entry.find('a', {'title': 'Abstract'})
            paper_id = paper_link['href'].split('/')[-1]
            arxiv_link = f"https://arxiv.org/abs/{paper_id}"
            
            # Extract title (remove "Title:" prefix)
            title_element = abstract.find('div', class_='list-title')
            title = title_element.text.replace('Title:', '').strip()
            
            # Extract authors (remove "Authors:" prefix)
            authors_element = abstract.find('div', class_='list-authors')
            authors = authors_element.text.replace('Authors:', '').strip()
            
            # Extract PDF link
            pdf_link = f"https://arxiv.org/pdf/{paper_id}.pdf"
            
            papers.append([
                title,
                authors,
                arxiv_link,
                pdf_link
            ])
            
            # Add a small delay to be respectful to the server
            time.sleep(0.5)
        
        return papers
        
    except requests.RequestException as e:
        print(f"Error fetching data: {e}")
        return None

def update_google_sheet(spreadsheet_id, papers, sheet_name):
    service = get_google_sheets_service()
    
    # Prepare the data
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    values = [
        ['Last Updated:', timestamp],
        [],  # Empty row for spacing
        ['Title', 'Authors', 'arXiv Link', 'PDF Link'],  # Header row
    ] + papers
    
    body = {
        'values': values
    }
    
    # Clear existing content
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f'{sheet_name}!A:D'
    ).execute()
    
    result = service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f'{sheet_name}!A1',  # Start from A1
        valueInputOption='RAW',
        body=body
    ).execute()
    
    print(f"{result.get('updatedCells')} cells updated.")

def find_new_papers(new_papers, existing_papers):
    """Find papers that are not in the existing papers list."""
    existing_titles = {paper[0] for paper in existing_papers}
    return [paper for paper in new_papers if paper[0] not in existing_titles]

def main():
    # Get Google Sheet ID from environment variable
    SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID', '1qpSVrXhaqwTWdnrc3fWtsJPbpPFV-IPx4hMwYNj08gA')
    
    print("Starting arXiv paper crawler...")
    service = get_google_sheets_service()
    
    # Get current date in YYMMDD format
    current_date = datetime.now().strftime('%y%m%d')
    
    # Get the latest sheet
    latest_sheet = get_latest_sheet(service, SPREADSHEET_ID)
    
    if latest_sheet:
        print(f"Found latest sheet: {latest_sheet}")
        # Get existing papers from the latest sheet
        existing_papers = get_existing_papers(service, SPREADSHEET_ID, latest_sheet)
        print(f"Found {len(existing_papers)} existing papers")
    else:
        print("No existing sheets found")
        existing_papers = []
    
    # Crawl new papers
    new_papers = crawl_arxiv_papers()
    
    if new_papers:
        print(f"Found {len(new_papers)} papers")
        
        # Find truly new papers
        unique_new_papers = find_new_papers(new_papers, existing_papers)
        
        if unique_new_papers:
            print(f"Found {len(unique_new_papers)} new papers")
            
            # Create new sheet with current date
            if create_new_sheet(service, SPREADSHEET_ID, current_date):
                print(f"Created new sheet: {current_date}")
                # Update the new sheet with all papers
                update_google_sheet(SPREADSHEET_ID, new_papers, current_date)
                print("Successfully updated new sheet!")
            else:
                print("Failed to create new sheet")
        else:
            print("No new papers found")
    else:
        print("No papers were found or an error occurred.")

if __name__ == "__main__":
    main() 
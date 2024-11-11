from pathlib import Path
from datetime import datetime
from typing import List, Optional
import re
from dataclasses import dataclass
from loguru import logger
import json
import PyPDF2


@dataclass
class TradeLeg:
    action: str
    quantity: int
    symbol: str
    expiration: Optional[datetime]
    option_type: Optional[str]
    strike: Optional[float]
    fill_price: float
    fill_time: datetime


@dataclass
class Trade:
    order_id: str
    date_received: datetime
    order_type: str
    legs: List[TradeLeg]


class EmailParser:
    """Parser for TastyTrade confirmation emails."""

    REGEX_PATTERNS = {
        'order_id': r'order\s*#\s*(\d+)',
        'date_received': r'Received\s*At:?\s*([A-Za-z]+\s*\d+\s*\d*,?\s*\d{4}\s+\d+\s*\d*:?\d+\s*:?\d+\s*\d*\s*('
                         r'?:AM|PM)\s+E[DS]T)',
        'order_type': r'Submitted\s+Order\s+T?ype:?\s*([^\n]+?)(?=\s*Fill|$)',
        'legs': r'(?:(?:Bought|Sold)\s+\d+\s+[A-Z]+(?:\s+\d+)*\s+(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\s*\d*/\d{1,2}/\d{2,4})?\s*(?:Put|Call)?\s*\d+\.?\d*\s+@\s+\d+\.?\d*)',
    }

    LEG_PATTERN = (
        r'(Bought|Sold)\s+'  # Action
        r'(\d+)\s+'  # Quantity
        r'([A-Z]+)'  # Symbol
        r'(?:\s+\d+)*\s+'  # Optional additional numbers
        r'(\d{1,2}/\d{1,2}/\d{2,4})\s+'  # Expiration date
        r'(Put|Call)\s+'  # Option type
        r'(\d+\.?\d*)\s+'  # Strike price
        r'@\s+'  # @ separator
        r'(\d+\.?\d*)'  # Fill price
        r'(?:.*?Filled\s+at:\s*(.*?(?:AM|PM)\s+E[DS]T))?'  # Fill time
    )

    @staticmethod
    def parse_datetime(date_str: str) -> datetime:
        """Convert date string to datetime object."""
        try:
            # Normalize the date string
            date_str = re.sub(r'(\d+:\d+:\d+)\s+A\s*M', r'\1 AM', date_str)
            date_str = re.sub(r'(\d+:\d+:\d+)\s+P\s*M', r'\1 PM', date_str)
            date_str = re.sub(r'E\s*([DS]T)', r'E\1', date_str)
            date_str = re.sub(r'([A-Za-z]+)\s+(\d+)\s+(\d+)', r'\1 \2\3', date_str)
            date_str = ' '.join(date_str.split())

            try:
                return datetime.strptime(date_str.strip(), "%b %d, %Y %I:%M:%S %p EDT")
            except ValueError:
                return datetime.strptime(date_str.strip(), "%b %d, %Y %I:%M:%S %p EST")
        except ValueError as e:
            logger.error(f"Error parsing date: {date_str}. Error: {e}")
            raise

    def parse_leg(self, leg_text: str) -> TradeLeg:
        """Parse individual trade leg details."""
        match = re.search(self.LEG_PATTERN, leg_text, re.DOTALL)
        if not match:
            logger.error(f"Failed to parse leg: {leg_text}")
            raise ValueError(f"Invalid leg format: {leg_text}")

        action, qty, symbol, exp, opt_type, strike, price, fill_time = match.groups()

        if not fill_time:
            if fill_time_match := re.search(
                self.REGEX_PATTERNS['fill_time'], leg_text
            ):
                fill_time = fill_time_match[1]
            else:
                logger.error(f"No fill time found for leg: {leg_text}")
                raise ValueError("No fill time found in leg text")

        # Handle stock trades (no expiration/option type/strike)
        expiration = datetime.strptime(exp, "%m/%d/%y") if exp else None
        return TradeLeg(
            action=action,
            quantity=int(qty),
            symbol=symbol,
            expiration=expiration,
            option_type=opt_type or None,
            strike=float(strike) if strike else None,
            fill_price=float(price),
            fill_time=self.parse_datetime(fill_time)
        )

    def parse_email(self, content: str) -> Trade:
        """Parse email content and return Trade object."""
        try:
            # Clean up the content
            content = content.replace('\n', ' ').replace('\r', ' ')
            content = ' '.join(content.split())

            logger.debug("Cleaning up content...")

            # Extract basic trade information
            order_id_match = re.search(self.REGEX_PATTERNS['order_id'], content, re.IGNORECASE)
            if not order_id_match:
                logger.error("Could not find order ID in content")
                raise ValueError("No order ID found")
            order_id = order_id_match[1]

            date_received_match = re.search(self.REGEX_PATTERNS['date_received'], content)
            if not date_received_match:
                logger.error("Could not find date received in content")
                logger.debug(f"Content: {content}")
                raise ValueError("No date received found")
            date_received = self.parse_datetime(date_received_match[1])

            order_type_match = re.search(self.REGEX_PATTERNS['order_type'], content)
            if not order_type_match:
                logger.error("Could not find order type in content")
                raise ValueError("No order type found")
            order_type = order_type_match[1].strip()

            # Extract legs with their associated fill times
            leg_sections = []
            fill_details_section = re.search(r'Fill\s+Details(.*?)(?:If you have any questions|$)', content, re.DOTALL)

            if fill_details_section:
                fill_content = fill_details_section.group(1)
                # Split the fill details section by "Filled at:" to get individual legs
                leg_parts = re.split(r'(?=(?:Bought|Sold)\s+\d+\s+[A-Z]+)', fill_content)
                leg_parts = [part.strip() for part in leg_parts if part.strip()]

                for part in leg_parts:
                    if re.search(r'(Bought|Sold)', part):
                        leg_sections.append(part)

            if not leg_sections:
                logger.error("No legs found in content")
                logger.debug(f"Fill content: {fill_content if 'fill_content' in locals() else 'No fill content found'}")
                raise ValueError("No trade legs found")

            legs = []
            for leg_section in leg_sections:
                try:
                    leg = self.parse_leg(leg_section)
                    legs.append(leg)
                except ValueError as e:
                    logger.warning(f"Failed to parse leg: {e}. Leg text: {leg_section}")
                    continue

            if not legs:
                raise ValueError("No valid legs parsed")

            return Trade(
                order_id=order_id,
                date_received=date_received,
                order_type=order_type,
                legs=legs
            )

        except (AttributeError, ValueError) as e:
            logger.error(f"Error parsing email content: {e}")
            raise


class TradeProcessor:
    """Process and store trade information."""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.parser = EmailParser()

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text content from PDF file."""
        try:
            text = ""
            with pdf_path.open('rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            logger.debug("Extracted text from PDF.")
            return text
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            raise

    def preprocess_pdf_text(self, text: str) -> str:
        """Clean up text extracted from PDF."""
        # Remove any weird spacing around common tokens
        text = re.sub(r'Received\s+At', 'Received At:', text)
        text = re.sub(r'Order\s+T\s*ype', 'Order Type:', text)
        text = re.sub(r'Filled\s+at:+', 'Filled at:', text)  # Normalize multiple colons

        # Fix specific PDF extraction artifacts
        text = re.sub(r'T\s+ype', 'Type', text)
        text = re.sub(r':+', ':', text)  # Replace multiple colons with single colon

        # Normalize whitespace
        text = ' '.join(text.split())

        # Remove any PDF artifacts
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'\d{1,2}/\d{1,2}/\d{4},\s+\d{1,2}:\d{2}', '', text)

        logger.debug(f"Preprocessed text: {text}")
        return text

    def process_email_file(self, file_path: Path) -> None:
        """Process email content from file and store results."""
        try:
            logger.info(f"Processing file: {file_path}")

            # Extract text from PDF
            content = self.extract_text_from_pdf(file_path)

            # Preprocess the content
            content = self.preprocess_pdf_text(content)

            # Parse the content
            trade = self.parser.parse_email(content)

            # Convert trade to dict for JSON storage
            trade_dict = {
                'order_id': trade.order_id,
                'date_received': trade.date_received.isoformat(),
                'order_type': trade.order_type,
                'legs': [
                    {
                        'action': leg.action,
                        'quantity': leg.quantity,
                        'symbol': leg.symbol,
                        'expiration': leg.expiration.isoformat(),
                        'option_type': leg.option_type,
                        'strike': leg.strike,
                        'fill_price': leg.fill_price,
                        'fill_time': leg.fill_time.isoformat()
                    }
                    for leg in trade.legs
                ]
            }

            # Save to JSON file
            output_file = self.output_path / f"trade_{trade.order_id}.json"
            with output_file.open('w') as f:
                json.dump(trade_dict, f, indent=4)

            logger.success(f"Successfully processed trade {trade.order_id}")

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            raise


def main():
    """Main entry point for the script."""
    logger.add("trades.log", rotation="500 MB")

    # Setup paths
    data_dir = Path("data")
    output_path = Path("output")
    output_path.mkdir(exist_ok=True)

    # Process all PDF files in data directory
    processor = TradeProcessor(output_path)

    # Get all PDF files in the data directory
    pdf_files = list(data_dir.glob("*.pdf"))

    if not pdf_files:
        logger.warning(f"No PDF files found in {data_dir}")
        return

    logger.info(f"Found {len(pdf_files)} PDF files to process")

    # Process each PDF file
    for pdf_file in pdf_files:
        try:
            logger.info(f"Processing file: {pdf_file.name}")
            processor.process_email_file(pdf_file)
            logger.success(f"Successfully processed {pdf_file.name}")
        except Exception as e:
            logger.error(f"Failed to process {pdf_file.name}: {str(e)}")
            continue  # Continue with next file even if one fails

    logger.info("Completed processing all files")

    # Print summary of processed files
    successful_trades = len(list(output_path.glob("*.json")))
    logger.info(f"Summary: Processed {len(pdf_files)} files, generated {successful_trades} trade records")


if __name__ == "__main__":
    main()

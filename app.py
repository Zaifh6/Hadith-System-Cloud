import os
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request, redirect, url_for
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import re
import uuid
import html
import json
import logging

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# PostgreSQL Connection Configuration
DB_HOST = os.environ.get('SUPABASE_DB_HOST')
DB_PORT = os.environ.get('SUPABASE_DB_PORT', '5432')
DB_NAME = os.environ.get('SUPABASE_DB_NAME')
DB_USERNAME = os.environ.get('SUPABASE_DB_USER')
DB_PASSWORD = os.environ.get('SUPABASE_DB_PASSWORD')
DATABASE_URL = f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create SQLAlchemy engine
try:
    engine = create_engine(DATABASE_URL)
    # Test connection
    with engine.connect() as conn:
        logger.info("✅ Connected to PostgreSQL successfully!")
except SQLAlchemyError as e:
    logger.error(f"❌ Connection failed: {e}")
    raise

def clean_sanad_chain(text):
    """Clean up a sanad chain by removing repeated عن words"""
    if not text:
        return ""
    # Replace multiple consecutive occurrences of 'عن' with a single one
    cleaned = re.sub(r'عن\s+عن\s+عن\s+', ' عن ', text)
    cleaned = re.sub(r'عن\s+عن\s+', ' عن ', cleaned)
    cleaned = re.sub(r'عن\s+و\s+', ' و ', cleaned)
    return cleaned

def get_table_prefix():
    lang = request.args.get('lang', 'ar')
    if lang not in ['ar', 'en']:
        lang = 'ar'
    return f"{lang}_", lang

def get_hadith_with_details(hadith_id, conn, lang='ar'):
    """Common function to get hadith details by ID"""
    prefix = f"{lang}_"
    # Get specific hadith by ID
    hadith_query = text(f"""
        SELECT 
            h.uuid,
            h.hadith_id,
            h.volume,
            h.page_number,
            hc.content AS hadith_content,
            b.id AS book_id,
            b.title AS book_title,
            h.originated_from
        FROM {prefix}hadith h
        JOIN {prefix}hadith_content hc ON h.hadith_content_id = hc.uuid
        JOIN {prefix}books b ON h.book_id = b.id
        WHERE h.hadith_id = :hadith_id
    """)
    
    hadith_result = conn.execute(hadith_query, {"hadith_id": hadith_id}).fetchone()
    
    if not hadith_result:
        return None
    
    hadith_uuid = hadith_result.uuid
    hadith_content = hadith_result.hadith_content
    originated_from = hadith_result.originated_from
    book_title = hadith_result.book_title
    page_num = hadith_result.page_number
    volume = hadith_result.volume
    
    logger.info(f"Processing hadith ID: {hadith_id}, UUID: {hadith_uuid}")
    
    # Get all sanads for this hadith using the new query
    sanad_query = text(f"""
        SELECT 
            hs.id AS sanad_id,
            hs.sanad_number,
            hs.sanad_description
        FROM {prefix}hadith h
        JOIN {prefix}hadith_sanads hs ON h.uuid = hs.hadith_id
        WHERE h.hadith_id = :hadith_id
        ORDER BY hs.sanad_number
    """)
    
    sanad_results = conn.execute(sanad_query, {"hadith_id": hadith_id}).fetchall()
    logger.info(f"Found {len(sanad_results)} sanad records")
    
    # Process each sanad
    all_sanad_entries = []
    for sanad in sanad_results:
        sanad_id = sanad.sanad_id
        
        # Get narrators for this sanad
        narrators_query = text(f"""
            SELECT 
                hnc.position, 
                n.id AS narrator_id, 
                n.name AS narrator_name,
                nd.reliability
            FROM {prefix}hadith_narrator_chain hnc
            JOIN {prefix}narrators n ON hnc.narrator_id = n.id
            LEFT JOIN {prefix}narrator_details nd ON n.id = nd.narrator_id
            WHERE hnc.sanad_id = :sanad_id
            ORDER BY hnc.position
        """)
        
        narrators = conn.execute(narrators_query, {"sanad_id": sanad_id}).fetchall()
        
        # Get special narrators for this sanad
        special_narrators_query = text(f"""
            SELECT 
                snr.id AS special_narrator_id,
                snr.name AS special_narrator_name,
                snr.ravi_id,
                n.id AS narrator_id,
                n.name AS narrator_name
            FROM {prefix}special_narrator_relations snr
            LEFT JOIN {prefix}special_narrator_narrator_relations snnr ON snr.id = snnr.special_narrator_id
            LEFT JOIN {prefix}narrators n ON snnr.narrator_id = n.id
            WHERE snr.hadith_uuid = :hadith_uuid AND snr.sanad_id = :sanad_id
        """)
        
        special_narrators = conn.execute(special_narrators_query, {"hadith_uuid": hadith_uuid, "sanad_id": sanad_id}).fetchall()
        
        # Process special narrators
        special_narrator_mapping = {}
        for special_narrator in special_narrators:
            if special_narrator.special_narrator_name:
                special_narrator_mapping[special_narrator.special_narrator_name] = {
                    'special_narrator_id': special_narrator.special_narrator_id,
                    'narrator_id': special_narrator.narrator_id,
                    'narrator_name': special_narrator.narrator_name
                }
        
        # Format narrator chain
        narrator_list = []
        narrator_names = []
        for narrator in narrators:
            narrator_list.append({
                "position": narrator.position,
                "narrator_id": narrator.narrator_id,
                "narrator_name": narrator.narrator_name,
                "reliability": narrator.reliability
            })
            narrator_names.append(narrator.narrator_name)
        
        formatted_chain = " عن ".join(narrator_names)
        formatted_chain = clean_sanad_chain(formatted_chain)
        
        # Create a custom sanad description with narrator IDs embedded
        sanad_desc = sanad.sanad_description if sanad.sanad_description else formatted_chain
        custom_sanad_desc = sanad_desc
        
        # Replace narrator names in the description with IDs
        for narrator in sorted(narrator_list, key=lambda x: len(x["narrator_name"]), reverse=True):
            name = narrator["narrator_name"]
            narrator_id = narrator["narrator_id"]
            if name and name in custom_sanad_desc:
                custom_sanad_desc = custom_sanad_desc.replace(name, f"[NARRATOR:{narrator_id}:{name}]")
        
        all_sanad_entries.append({
            "path_num": sanad.sanad_number,
            "sanad_id": sanad.sanad_id,
            "narrators": narrator_list,
            "formatted_chain": formatted_chain,
            "sanad_description": sanad.sanad_description,
            "custom_sanad_desc": custom_sanad_desc,
            "special_narrators": special_narrator_mapping
        })
    
    logger.info(f"Found {len(all_sanad_entries)} sanad entries")
    
    # Get reference entries with the new query
    reference_entries = []
    try:
        logger.info("Getting reference entries...")
        reference_query = text(f"""
            SELECT 
                h.hadith_id AS original_hadith_id,
                r.hadith_id AS reference_hadith_id,
                r.volume AS reference_volume,
                r.page_num AS reference_page,
                r.source_id,
                r.source_title
            FROM {prefix}hadith h
            JOIN {prefix}reference r ON h.uuid = r.hadith_uuid
            WHERE h.hadith_id = :hadith_id
            ORDER BY r.source_title, r.volume, r.page_num
        """)
        
        reference_results = conn.execute(reference_query, {"hadith_id": hadith_id}).fetchall()
        
        for row in reference_results:
            reference_entries.append({
                "hadithId": row.reference_hadith_id,
                "vol": row.reference_volume,
                "pageNum": row.reference_page,
                "sourceId": row.source_id,
                "sourceMainTitle": row.source_title
            })
        
        logger.info(f"Found {len(reference_entries)} reference entries")
    except Exception as e:
        logger.error(f"Error processing references: {str(e)}")
    
    # Get translation if available
    translation_query = text(f"""
        SELECT id, translation 
        FROM {prefix}hadith_translations 
        WHERE hadith_id = :hadith_uuid 
        AND language = 'english'
        LIMIT 1
    """)
    
    translation_result = conn.execute(translation_query, {"hadith_uuid": hadith_uuid}).fetchone()
    translation_count = 1 if translation_result else 0
    translation_text = translation_result.translation if translation_result else ""
    
    # Handle other fields or set defaults
    hadith_title = f"{book_title} {volume} ج {page_num} ص"
    hadith_chapter = ""
    hadith_section = ""
    
    # Process sanad for display
    if all_sanad_entries:
        first_sanad = all_sanad_entries[0]
        sanad_description = first_sanad["sanad_description"]
        sanad_arabic = first_sanad["sanad_description"]
    else:
        sanad_description = "Sanad information not available."
        sanad_arabic = "معلومات السند غير متوفرة"
    
    # Set dummy values for fields we don't have in our schema
    explanation_count = 0
    explanation_text = ""
    related_hadiths_count = 0
    same_topic_hadiths_count = 0
    
    return {
        "hadith_id": hadith_id,
        "hadith_content": hadith_content,
        "originated_from": originated_from,
        "book_title": book_title,
        "page_num": page_num,
        "volume": volume,
        "hadith_uuid": hadith_uuid,
        "sanad_description": sanad_description,
        "sanad_arabic": sanad_arabic,
        "hadith_title": hadith_title,
        "hadith_chapter": hadith_chapter,
        "hadith_section": hadith_section,
        "related_hadiths_count": related_hadiths_count,
        "same_topic_hadiths_count": same_topic_hadiths_count,
        "translation_count": translation_count,
        "translation_text": translation_text,
        "explanation_count": explanation_count,
        "explanation_text": explanation_text,
        "sanad_entries": all_sanad_entries,
        "reference_entries": reference_entries
    }

@app.route('/')
def index():
    try:
        with engine.connect() as conn:
            prefix, lang = get_table_prefix()
            # First check if we have data in the database
            check_query = text(f"SELECT COUNT(*) FROM {prefix}hadith")
            count = conn.execute(check_query).scalar()
            logger.info(f"Found {count} hadith records in database")
            
            if count == 0:
                return "No data found in the database. Please add some data first.", 404
            
            # Get the first hadith ID
            hadith_id_query = text(f"SELECT hadith_id FROM {prefix}hadith ORDER BY hadith_id LIMIT 1")
            first_hadith_id = conn.execute(hadith_id_query).scalar()
            
            if not first_hadith_id:
                return "No hadith found in the database", 404
            
            # Get full hadith details using the common function
            hadith_data = get_hadith_with_details(first_hadith_id, conn, lang)
            
            if not hadith_data:
                return "Failed to retrieve hadith data", 500
                
    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}")
        return f"Database error: {str(e)}", 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return f"Unexpected error: {str(e)}", 500

    # Pass the data to the HTML template
    return render_template('index.html', **hadith_data, lang=lang)

@app.route('/hadith/<hadith_id>')
def show_hadith(hadith_id):
    """
    Route to display a specific hadith by ID
    """
    try:
        with engine.connect() as conn:
            prefix, lang = get_table_prefix()
            # Get full hadith details using the common function
            hadith_data = get_hadith_with_details(hadith_id, conn, lang)
            
            if not hadith_data:
                return f"Hadith with ID {hadith_id} not found", 404
                
    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}")
        return f"Database error: {str(e)}", 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return f"Unexpected error: {str(e)}", 500

    # Pass the data to the HTML template
    return render_template('index.html', **hadith_data, lang=lang)

@app.route('/search_hadith')
def search_hadith():
    """
    Route to handle hadith search by ID from the search form
    """
    hadith_id = request.args.get('hadith_id', '')
    lang = request.args.get('lang', 'ar')
    if hadith_id:
        # Redirect to the hadith page with the provided ID
        return redirect(url_for('show_hadith', hadith_id=hadith_id, lang=lang))
    else:
        # If no ID is provided, redirect to the homepage
        return redirect(url_for('index', lang=lang))

@app.route('/api/hadith/<hadith_id>')
def get_hadith_api(hadith_id):
    try:
        with engine.connect() as conn:
            prefix, lang = get_table_prefix()
            # API endpoint for fetching a specific hadith
            query = text(f"""
                SELECT 
                    h.uuid,
                    h.hadith_id,
                    hc.content AS text,
                    b.title AS book,
                    h.volume,
                    h.page_number AS page,
                    h.originated_from AS narrator
                FROM {prefix}hadith h
                JOIN {prefix}hadith_content hc ON h.hadith_content_id = hc.uuid
                JOIN {prefix}books b ON h.book_id = b.id
                WHERE h.hadith_id = :hadith_id
            """)
            
            result = conn.execute(query, {"hadith_id": hadith_id}).fetchone()
            
            if not result:
                return jsonify({"error": "Hadith not found"}), 404
            
            # Transform data for API response
            response = {
                "id": result.hadith_id,
                "text": result.text,
                "book": result.book,
                "volume": result.volume,
                "page": result.page,
                "narrator": result.narrator
            }
            
            return jsonify(response)
            
    except SQLAlchemyError as e:
        logger.error(f"API database error: {str(e)}")
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"API unexpected error: {str(e)}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@app.route('/api/narrator/<narrator_id>')
def get_narrator_details(narrator_id):
    try:
        with engine.connect() as conn:
            prefix, lang = get_table_prefix()
            logger.info(f"Fetching narrator {narrator_id} with prefix: {prefix}, lang: {lang}")
            
            # Get narrator details
            query = text(f"""
                SELECT 
                    n.id,
                    n.name,
                    nd.reliability,
                    nd.titles,
                    nd.patronymic,
                    nd.sect
                FROM {prefix}narrators n
                LEFT JOIN {prefix}narrator_details nd ON n.id = nd.narrator_id
                WHERE n.id = :narrator_id
            """)
            
            result = conn.execute(query, {"narrator_id": narrator_id}).fetchone()
            
            if not result:
                return jsonify({"error": "Narrator not found"}), 404
            
            # Get death records
            death_query = text(f"""
                SELECT 
                    source,
                    death_year
                FROM {prefix}narrator_death_records
                WHERE narrator_id = :narrator_id
            """)
            
            death_records = conn.execute(death_query, {"narrator_id": narrator_id}).fetchall()
            
            # Get evaluations
            evaluation_query = text(f"""
                SELECT 
                    source,
                    evaluation,
                    summary
                FROM {prefix}narrator_evaluation
                WHERE narrator_id = :narrator_id
            """)
            
            evaluations = conn.execute(evaluation_query, {"narrator_id": narrator_id}).fetchall()
            
            logger.info(f"Found {len(evaluations)} evaluations for narrator {narrator_id}")
            for i, eval in enumerate(evaluations):
                logger.info(f"Evaluation {i+1}: source='{eval.source}', evaluation='{eval.evaluation}', summary='{eval.summary}'")
            
            # Check if we need to get English translations from a different source
            # For now, let's see if the evaluation content is actually different between languages
            # If both tables contain the same Arabic content, we might need to handle this differently
            
            # Format response
            narrator_details = {
                "id": result.id,
                "name": result.name,
                "reliability": result.reliability or "",
                "titles": result.titles or "",
                "patronymic": result.patronymic or "",
                "sect": result.sect or "",
                "death_records": [{"source": r.source, "death_year": r.death_year} for r in death_records],
                "evaluations": [{"source": r.source, "evaluation": r.evaluation, "summary": r.summary} for r in evaluations],
                "lang": lang,  # Add language info for debugging
                "table_prefix": prefix  # Add table prefix for debugging
            }
            
            return jsonify(narrator_details)
            
    except SQLAlchemyError as e:
        logger.error(f"API database error: {str(e)}")
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"API unexpected error: {str(e)}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@app.route('/narrator/<narrator_id>')
def show_narrator(narrator_id):
    """
    Route to display a specific narrator by ID in a webpage
    """
    try:
        with engine.connect() as conn:
            prefix, lang = get_table_prefix()
            # Get narrator details
            query = text(f"""
                SELECT 
                    n.id,
                    n.name,
                    nd.reliability,
                    nd.titles,
                    nd.patronymic,
                    nd.sect
                FROM {prefix}narrators n
                LEFT JOIN {prefix}narrator_details nd ON n.id = nd.narrator_id
                WHERE n.id = :narrator_id
            """)
            
            result = conn.execute(query, {"narrator_id": narrator_id}).fetchone()
            
            if not result:
                return f"Narrator with ID {narrator_id} not found", 404
            
            # Get death records
            death_query = text(f"""
                SELECT 
                    source,
                    death_year
                FROM {prefix}narrator_death_records
                WHERE narrator_id = :narrator_id
            """)
            
            death_records = conn.execute(death_query, {"narrator_id": narrator_id}).fetchall()
            
            # Get evaluations
            evaluation_query = text(f"""
                SELECT 
                    source,
                    evaluation,
                    summary
                FROM {prefix}narrator_evaluation
                WHERE narrator_id = :narrator_id
            """)
            
            evaluations = conn.execute(evaluation_query, {"narrator_id": narrator_id}).fetchall()
            
            # Format data for template
            narrator_data = {
                "id": result.id,
                "name": result.name,
                "reliability": result.reliability or "",
                "titles": result.titles or "",
                "patronymic": result.patronymic or "",
                "sect": result.sect or "",
                "death_records": [{"source": r.source, "death_year": r.death_year} for r in death_records],
                "evaluations": [{"source": r.source, "evaluation": r.evaluation, "summary": r.summary} for r in evaluations]
            }
                
    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}")
        return f"Database error: {str(e)}", 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return f"Unexpected error: {str(e)}", 500

    # Pass the data to the HTML template
    return render_template('narrator.html', **narrator_data, lang=lang)

if __name__ == '__main__':
    app.run(debug=True)
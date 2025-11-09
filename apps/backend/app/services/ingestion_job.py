import logging
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import DataSource
from app.data_providers import GithubDataProvider
from app.core import settings

from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat

logger = logging.getLogger(__name__)

class IngestionJobService:
    def __init__(self, db: Session):
        self.db = db 
    

    def run_ingestion_job(self, data_source_id):
        
        # retrieve data source 
        stmt = select(DataSource).where(DataSource.id == data_source_id)
        data_source = self.db.execute(stmt).scalar_one_or_none()

        if not data_source:
            raise Exception('Invalid specified Data Source ID to ingest data from')

        # use data source information to fetch relevant data & store in temp directory 
        self._retrieve_data(data_source)

        #TODO: Use docling to convert all files in /tmp/docs to .md 


        # retrieve chroma DB collection 

        # use relevant chunking mechanism based on content type 

        # use vector store index to ingest data 
        return None
    


    def _retrieve_data(self, data_source: DataSource):
        """
        Retrieve relevant data from specified Data Source and store within temporary /data directory 
        in order to be ingested into Chroma DB 

        NOTE: In future, we should make some sort of "diff" calculation each time we retreive data from data source 
        in order to quickly determine what's already been retireving before
        """

        code_path, docs_path = self._create_tmp_dirs()

        # retrieve data based on provider & store within temp directory
        match data_source.provider:
            case 'GitHub':
                logger.info(f'Attempting to retrieve data from GitHub provider for URL: {data_source.url}')
                provider = GithubDataProvider(url=data_source.url)
                provider.ingest_data()
            case _:
                logger.error(f"The specified Data Source provider is not configured for this application") 
        
        # convert any docs to unified markdown format 
        self._convert_docs_to_markdown()
        
        # iterate through each file and chunk intelligently 

        # retrieve relevant projects corresponding to Data Source 


        # retrieve embedding 

        # use ChromaVectorStore to store 

        self._cleanup_tmp_dirs(code_path, docs_path)





    def _create_tmp_dirs(self):
        """
        Create temporary directory for storing downloaded code and documentation files 
        """

        docs_path = Path(settings.TMP_DOCS)
        docs_path.mkdir(exist_ok=True, parents=True)
        code_path = Path(settings.TMP_CODE)
        code_path.mkdir(exist_ok=True, parents=True)

        return code_path, docs_path
    


    def _convert_docs_to_markdown(self):
        """
        Convert each temporary document downloaded to a markdown file 
        """

        # convert configured docs file extensions to docling InputFormats
        allowed_formats = [ InputFormat(allowed_format.lower()) for allowed_format in settings.DOCS_FILE_EXTENSIONS ]

        # create converter for creating Docling Documents from our local files
        docs_converter = DocumentConverter(
            allowed_formats=allowed_formats 
            #TODO: Consider looking through specific formatting for specific file types 
        )

        # retrieve list of files from tmp docs 
        tmp_docs = Path(settings.TMP_DOCS)
        input_files = list(tmp_docs.glob("**/*")) 
        filtered_doc_files = [f for f in input_files if f.is_file()] # only retrieve files

        # convert all docs files to Docling Docs
        conv_results = docs_converter.convert_all(filtered_doc_files)

        # create processed docs dir to save md files to
        path = settings.TMP_DOCS + settings.PROCESSED_DIR
        out_path = Path(path)
        out_path.mkdir(exist_ok=True, parents=True)


        # write docling files as md files in processed dir
        for res in conv_results:
            file_name = f"{res.input.file.stem}.md"
            
            with open(out_path / f"{file_name}", "w") as fp:
                fp.write(res.document.export_to_markdown())
        

    def _cleanup_tmp_dirs(self, code_path: Path, docs_path: Path):
        """
        Remove files from temporary directory and remove directory altogether 

        Args:
            code_path: directory storing code files 
            docs_path: directory storing docs files
        """                 

        for path in [code_path, docs_path]:

            # remove files            
            for file_path in path.iterdir():
                if file_path.is_file():
                    file_path.unlink()

            # remove child dir 
            path.rmdir()  
        

        # remove /tmp/docs/processed 
        path = Path(settings.TMP_DOCS + settings.PROCESSED_DIR)
        path.rmdir()

        # remove /tmp parent dir 
        path = Path(settings.TMP)
        path.rmdir()
        


        





    

        


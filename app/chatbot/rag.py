"""
Retrieval-Augmented Generation (RAG) Pipeline for the Patient360 Chatbot.

This module implements a RAG pipeline for retrieving medical knowledge
and providing accurate responses to user queries. It supports PDF uploads
for expanding the knowledge base.
"""

import os
import json
import uuid
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI

# Import from task_store instead of pdf_api to avoid circular imports
from app.chatbot.task_store import background_tasks, save_background_tasks

# Disable ChromaDB telemetry
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PDF processing imports
try:
    from pypdf import PdfReader
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    PDF_SUPPORT = True
except ImportError:
    logger.warning("PDF support libraries not installed. PDF processing will be disabled.")
    PDF_SUPPORT = False


class PDFProcessor:
    """
    PDF Processing Utility for extracting and chunking text from PDFs.
    """
    
    @staticmethod
    def extract_text_from_pdf(pdf_path: str) -> str:
        """
        Extract text from a PDF file.
        
        Args:
            pdf_path: Path to the PDF file.
            
        Returns:
            The extracted text.
        """
        if not PDF_SUPPORT:
            raise ImportError("PDF support libraries not installed. Please install pypdf and langchain.")
            
        try:
            reader = PdfReader(pdf_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            raise

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
        """
        Split text into chunks for embedding.
        
        Args:
            text: The text to chunk.
            chunk_size: The size of each chunk.
            chunk_overlap: The overlap between chunks.
            
        Returns:
            A list of text chunks.
        """
        if not PDF_SUPPORT:
            raise ImportError("PDF support libraries not installed. Please install pypdf and langchain.")
            
        try:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
                separators=["\n\n", "\n", " ", ""]
            )
            chunks = text_splitter.split_text(text)
            return chunks
        except Exception as e:
            logger.error(f"Error chunking text: {e}")
            raise

    @staticmethod
    def prepare_knowledge_items(
        chunks: List[str], 
        source: str, 
        topic: str, 
        audience: str = "clinician"
    ) -> List[Dict[str, Any]]:
        """
        Prepare knowledge items for the RAG pipeline.
        
        Args:
            chunks: The text chunks.
            source: The source of the knowledge (e.g., book title).
            topic: The topic of the knowledge.
            audience: The target audience (patient or clinician).
            
        Returns:
            A list of knowledge items.
        """
        knowledge_items = []
        for i, chunk in enumerate(chunks):
            item_id = f"{source.lower().replace(' ', '-')}-{i}-{uuid.uuid4().hex[:8]}"
            knowledge_items.append({
                "id": item_id,
                "text": chunk,
                "metadata": {
                    "source": source,
                    "topic": topic,
                    "subtopic": f"chunk-{i}",
                    "audience": audience,
                    "page": i  # This is approximate and doesn't correspond to actual PDF pages
                }
            })
        return knowledge_items


class RAGPipeline:
    """
    Retrieval-Augmented Generation (RAG) Pipeline.
    
    This class implements a RAG pipeline for retrieving medical knowledge
    and providing accurate responses to user queries.
    """
    
    def __init__(self, collection_name: str = "medical_knowledge"):
        """Initialize the RAG pipeline."""
        # Initialize Chroma client with updated configuration
        self.client = chromadb.PersistentClient(
            path=os.path.join(os.getcwd(), "chroma_db")
        )
        
        # Create or get collection
        self.embedding_function = embedding_functions.OpenAIEmbeddingFunction(
            api_key=os.getenv("LLM_API_KEY"),
            model_name="text-embedding-3-large"
        )
        
        try:
            self.collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            logger.info(f"Retrieved existing collection: {collection_name}")
            
            # Check if collection is empty
            collection_count = self.collection.count()
            if collection_count == 0:
                logger.info("Collection is empty. Please upload knowledge through the admin interface.")
            else:
                logger.info(f"Collection contains {collection_count} items.")
                
        except ValueError:
            # Collection doesn't exist, create it
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            logger.info(f"Created new collection: {collection_name}")
            logger.info("Collection is empty. Please upload knowledge through the admin interface.")
    
    async def process_pdf(
        self,
        pdf_path: str,
        source: str,
        topic: str,
        audience: str = "clinician",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        task_id: str = None
    ) -> Tuple[int, List[str]]:
        """
        Process a PDF file and add its content to the knowledge base.
        
        Args:
            pdf_path: Path to the PDF file.
            source: The source of the knowledge (e.g., book title).
            topic: The topic of the knowledge.
            audience: The target audience (patient or clinician).
            chunk_size: The size of each chunk.
            chunk_overlap: The overlap between chunks.
            task_id: Optional task ID for progress tracking.
            
        Returns:
            A tuple of (number of chunks added, list of chunk IDs).
        """
        if not PDF_SUPPORT:
            raise ImportError("PDF support libraries not installed. Please install pypdf and langchain.")
            
        try:
            # Update task status if task_id is provided
            if task_id and task_id in background_tasks:
                background_tasks[task_id].update({
                    "status": "extracting_text",
                    "progress": 10,
                    "message": "Extracting text from PDF",
                    "last_updated": time.time()
                })
                # Save tasks to file
                save_background_tasks()
            
            # Extract text from PDF
            text = PDFProcessor.extract_text_from_pdf(pdf_path)
            
            # Update task status
            if task_id and task_id in background_tasks:
                background_tasks[task_id].update({
                    "status": "chunking_text",
                    "progress": 20,
                    "message": "Chunking text into segments",
                    "last_updated": time.time()
                })
                # Save tasks to file
                save_background_tasks()
            
            # Chunk the text
            chunks = PDFProcessor.chunk_text(text, chunk_size, chunk_overlap)
            
            # Update task status
            if task_id and task_id in background_tasks:
                background_tasks[task_id].update({
                    "status": "preparing_items",
                    "progress": 30,
                    "message": "Preparing knowledge items",
                    "total_chunks": len(chunks),
                    "last_updated": time.time()
                })
                # Save tasks to file
                save_background_tasks()
            
            # Prepare knowledge items
            knowledge_items = PDFProcessor.prepare_knowledge_items(chunks, source, topic, audience)
            
            # Update task status
            if task_id and task_id in background_tasks:
                background_tasks[task_id].update({
                    "status": "adding_to_database",
                    "progress": 40,
                    "message": "Adding items to vector database",
                    "last_updated": time.time()
                })
                # Save tasks to file
                save_background_tasks()
            
            # Add to RAG pipeline with task_id for progress tracking
            success = await self.add_knowledge(knowledge_items, task_id)
            
            if success:
                logger.info(f"Successfully added {len(chunks)} chunks from {pdf_path} to knowledge base")
                return len(chunks), [item["id"] for item in knowledge_items]
            else:
                logger.error(f"Failed to add chunks from {pdf_path} to knowledge base")
                return 0, []
        except Exception as e:
            logger.error(f"Error processing PDF to knowledge base: {e}")
            raise
    
    async def query(self, query_text: str, n_results: int = 3, audience: str = "patient") -> List[Dict[str, Any]]:
        """
        Query the RAG pipeline for relevant medical knowledge.
        
        Args:
            query_text: The query text.
            n_results: The number of results to return.
            audience: The target audience (patient or clinician).
            
        Returns:
            A list of relevant knowledge items.
        """
        try:
            # Prepare where clause to include general audience content
            where_clause = None
            if audience:
                if audience == "patient":
                    where_clause = {"audience": {"$in": ["patient", "general"]}}
                elif audience == "clinician":
                    where_clause = {"audience": {"$in": ["clinician", "general"]}}
                else:
                    where_clause = {"audience": audience}
            
            # Query the collection
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_clause
            )
            
            # Format results
            formatted_results = []
            if results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    formatted_results.append({
                        "text": doc,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else None
                    })
            
            return formatted_results
        
        except Exception as e:
            logger.error(f"Error querying RAG pipeline: {e}")
            return []
    
    async def add_knowledge(self, items: List[Dict[str, Any]], task_id: str = None) -> bool:
        """
        Add knowledge items to the RAG pipeline.
        
        Args:
            items: A list of knowledge items, each with id, text, and metadata.
            task_id: Optional task ID for progress tracking.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            # Process in batches to avoid token limits
            batch_size = 50  # Adjust based on average chunk size
            total_items = len(items)
            successful_items = 0
            
            for i in range(0, total_items, batch_size):
                batch = items[i:i+batch_size]
                
                # Extract data from the batch
                ids = [item["id"] for item in batch]
                texts = [item["text"] for item in batch]
                metadatas = [item["metadata"] for item in batch]
                
                # Add batch to collection
                self.collection.add(
                    ids=ids,
                    documents=texts,
                    metadatas=metadatas
                )
                
                successful_items += len(batch)
                
                # Update progress if task_id is provided
                if task_id and task_id in background_tasks:
                    progress = int((i + len(batch)) / total_items * 100)
                    background_tasks[task_id].update({
                        "progress": progress,
                        "chunks_processed": i + len(batch),
                        "total_chunks": total_items,
                        "message": f"Processing chunks: {i + len(batch)}/{total_items}",
                        "last_updated": time.time()
                    })
                    # Save tasks to file after each batch update
                    save_background_tasks()
                    logger.info(f"Task {task_id}: Processed {i + len(batch)}/{total_items} chunks ({progress}%)")
            
            logger.info(f"Added {successful_items} knowledge items to collection")
            return True
        
        except Exception as e:
            logger.error(f"Error adding knowledge: {e}")
            return False
    
    async def delete_knowledge(self, ids: List[str]) -> bool:
        """
        Delete knowledge items from the RAG pipeline.
        
        Args:
            ids: A list of knowledge item IDs to delete.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            # Delete from collection
            self.collection.delete(ids=ids)
            
            logger.info(f"Deleted {len(ids)} knowledge items from collection")
            return True
        
        except Exception as e:
            logger.error(f"Error deleting knowledge: {e}")
            return False
    
    async def update_knowledge(self, item: Dict[str, Any]) -> bool:
        """
        Update a knowledge item in the RAG pipeline.
        
        Args:
            item: The knowledge item to update, with id, text, and metadata.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            # Update in collection
            self.collection.update(
                ids=[item["id"]],
                documents=[item["text"]],
                metadatas=[item["metadata"]]
            )
            
            logger.info(f"Updated knowledge item: {item['id']}")
            return True
        
        except Exception as e:
            logger.error(f"Error updating knowledge: {e}")
            return False
    
    async def get_knowledge(self, id: str) -> Optional[Dict[str, Any]]:
        """
        Get a knowledge item from the RAG pipeline.
        
        Args:
            id: The ID of the knowledge item to get.
            
        Returns:
            The knowledge item, or None if not found.
        """
        try:
            # Get from collection
            result = self.collection.get(ids=[id])
            
            if result["documents"]:
                return {
                    "id": id,
                    "text": result["documents"][0],
                    "metadata": result["metadatas"][0] if result["metadatas"] else {}
                }
            
            return None
        
        except Exception as e:
            logger.error(f"Error getting knowledge: {e}")
            return None
    
    async def get_knowledge_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the knowledge base.
        
        Returns:
            Statistics about the knowledge base.
        """
        try:
            # Get all items
            all_items = self.collection.get()
            
            # Count by source
            sources = {}
            topics = {}
            audiences = {}
            
            if all_items["metadatas"]:
                for metadata in all_items["metadatas"]:
                    source = metadata.get("source", "unknown")
                    topic = metadata.get("topic", "unknown")
                    audience = metadata.get("audience", "unknown")
                    
                    sources[source] = sources.get(source, 0) + 1
                    topics[topic] = topics.get(topic, 0) + 1
                    audiences[audience] = audiences.get(audience, 0) + 1
            
            return {
                "total_items": len(all_items["ids"]) if all_items["ids"] else 0,
                "sources": sources,
                "topics": topics,
                "audiences": audiences
            }
        
        except Exception as e:
            logger.error(f"Error getting knowledge stats: {e}")
            return {
                "total_items": 0,
                "sources": {},
                "topics": {},
                "audiences": {}
            }


# Create a singleton instance of the RAG pipeline
rag_pipeline = RAGPipeline()
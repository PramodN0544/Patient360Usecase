"""
Retrieval-Augmented Generation (RAG) Pipeline for the Patient360 Chatbot.

This module implements a RAG pipeline for retrieving medical knowledge
and providing accurate responses to user queries.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default medical knowledge chunks for demonstration
DEFAULT_MEDICAL_KNOWLEDGE = [
    {
        "id": "diabetes-1",
        "text": "Diabetes is a chronic health condition that affects how your body turns food into energy. Most of the food you eat is broken down into sugar (glucose) and released into your bloodstream. When your blood sugar goes up, it signals your pancreas to release insulin. Insulin acts like a key to let the blood sugar into your body's cells for use as energy.",
        "metadata": {
            "source": "CDC",
            "topic": "diabetes",
            "subtopic": "overview",
            "audience": "patient"
        }
    },
    {
        "id": "diabetes-2",
        "text": "There are three main types of diabetes: Type 1, Type 2, and gestational diabetes. Type 1 diabetes is caused by an autoimmune reaction that stops your body from making insulin. Type 2 diabetes occurs when your body doesn't use insulin well and can't keep blood sugar at normal levels. Gestational diabetes develops in pregnant women who have never had diabetes.",
        "metadata": {
            "source": "CDC",
            "topic": "diabetes",
            "subtopic": "types",
            "audience": "patient"
        }
    },
    {
        "id": "hypertension-1",
        "text": "Hypertension, also known as high blood pressure, is a common condition in which the long-term force of the blood against your artery walls is high enough that it may eventually cause health problems, such as heart disease. Blood pressure is determined both by the amount of blood your heart pumps and the amount of resistance to blood flow in your arteries.",
        "metadata": {
            "source": "Mayo Clinic",
            "topic": "hypertension",
            "subtopic": "overview",
            "audience": "patient"
        }
    },
    {
        "id": "hypertension-2",
        "text": "Blood pressure readings are given as two numbers. The top number (systolic) is the pressure in your arteries when your heart beats. The bottom number (diastolic) is the pressure in your arteries when your heart rests between beats. Normal blood pressure is less than 120/80 mm Hg. Hypertension stage 1 is 130-139 or 80-89 mm Hg, and hypertension stage 2 is 140/90 mm Hg or higher.",
        "metadata": {
            "source": "American Heart Association",
            "topic": "hypertension",
            "subtopic": "diagnosis",
            "audience": "patient"
        }
    },
    {
        "id": "diabetes-clinical-1",
        "text": "The diagnostic criteria for diabetes mellitus include: Fasting plasma glucose ≥126 mg/dL (7.0 mmol/L), or 2-hour plasma glucose ≥200 mg/dL (11.1 mmol/L) during OGTT, or HbA1c ≥6.5% (48 mmol/mol), or random plasma glucose ≥200 mg/dL (11.1 mmol/L) in patients with classic symptoms of hyperglycemia. The test should be repeated to confirm the diagnosis unless unequivocal hyperglycemia is present.",
        "metadata": {
            "source": "American Diabetes Association",
            "topic": "diabetes",
            "subtopic": "diagnosis",
            "audience": "clinician"
        }
    },
    {
        "id": "hypertension-clinical-1",
        "text": "The 2017 ACC/AHA guidelines define hypertension as BP ≥130/80 mm Hg, while the ESC/ESH guidelines define it as BP ≥140/90 mm Hg. Initial evaluation should include assessment of cardiovascular risk factors, target organ damage, and secondary causes of hypertension. Ambulatory BP monitoring is recommended to confirm the diagnosis, identify white coat or masked hypertension, and evaluate BP control in treated patients.",
        "metadata": {
            "source": "ACC/AHA Guidelines",
            "topic": "hypertension",
            "subtopic": "diagnosis",
            "audience": "clinician"
        }
    }
]


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
            model_name="text-embedding-ada-002"
        )
        
        try:
            self.collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            logger.info(f"Retrieved existing collection: {collection_name}")
        except ValueError:
            # Collection doesn't exist, create it
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            logger.info(f"Created new collection: {collection_name}")
            
            # Add default medical knowledge
            self._add_default_knowledge()
    
    def _add_default_knowledge(self):
        """Add default medical knowledge to the collection."""
        try:
            # Extract data from the default knowledge
            ids = [item["id"] for item in DEFAULT_MEDICAL_KNOWLEDGE]
            texts = [item["text"] for item in DEFAULT_MEDICAL_KNOWLEDGE]
            metadatas = [item["metadata"] for item in DEFAULT_MEDICAL_KNOWLEDGE]
            
            # Add to collection
            self.collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas
            )
            
            logger.info(f"Added {len(ids)} default knowledge items to collection")
        except Exception as e:
            logger.error(f"Error adding default knowledge: {e}")
    
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
            # Query the collection
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where={"audience": audience} if audience else None
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
    
    async def add_knowledge(self, items: List[Dict[str, Any]]) -> bool:
        """
        Add knowledge items to the RAG pipeline.
        
        Args:
            items: A list of knowledge items, each with id, text, and metadata.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            # Extract data from the items
            ids = [item["id"] for item in items]
            texts = [item["text"] for item in items]
            metadatas = [item["metadata"] for item in items]
            
            # Add to collection
            self.collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas
            )
            
            logger.info(f"Added {len(ids)} knowledge items to collection")
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


# Create a singleton instance of the RAG pipeline
rag_pipeline = RAGPipeline()
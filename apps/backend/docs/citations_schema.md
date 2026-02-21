**Background**
We have two types of nodes in our ChromaDB instance:
1. Doc Nodes
2. Code Nodes

**Doc Nodes**

**TextNode.metadata._node_content**
```json 
{
  "id_": "17e990cc-3ca7-455b-92a1-4bce284f377a",
  "embedding": null,
  "metadata": {
    "chunk_idx": "CONTEXTUALIZED_42",
    "source": "README.md",
    "mimetype": "text/markdown",
    "headings": "React + Vite > Expanding the ESLint configuration",
    "document_hash": "15417426378862981789",
    "content_types": "code,text",
    "data_source_id": "76797406-12af-411c-81ee-c84da8cf1b30"
  },
  "excluded_embed_metadata_keys": [],
  "excluded_llm_metadata_keys": [],
  "relationships": {},
  "metadata_template": "{key}: {value}",
  "metadata_separator": "\n",
  "text": "",
  "mimetype": "text/plain",
  "start_char_idx": null,
  "end_char_idx": null,
  "metadata_seperator": "\n",
  "text_template": "{metadata_str}\n\n{content}",
  "class_name": "TextNode"
}
```

**TextNode.metadata**
```json 
{
    "source": "README.md",
    "content_types": "code,text",
    "document_hash": "15417426378862981789",
    "mimetype": "text/markdown",
    "data_source_id": "76797406-12af-411c-81ee-c84da8cf1b30",
    "_node_content": "...",
    "document_id": "None",
    "headings": "React + Vite > Expanding the ESLint configuration",
    "ref_doc_id": "None",
    "_node_type": "TextNode",
    "doc_id": "None",
    "chunk_idx": "CONTEXTUALIZED_42"
}
```


**Code Nodes**

**TextNode.metadata._node_content**
```json 
{
  "id_": "83c4f8d1-5293-4917-aef7-2da1dc50d92f",
  "embedding": null,
  "metadata": {
    "file_path": "/app/tmp/code/e996401e-3f8a-4098-8bad-3df4cb88ddbc/apps/backend/app/llm/providers/openai.py",
    "file_name": "openai.py",
    "file_type": "text/x-python",
    "file_size": 2107,
    "creation_date": "2026-02-21",
    "last_modified_date": "2026-02-21",
    "data_source_id": "76797406-12af-411c-81ee-c84da8cf1b30"
  },
  "excluded_embed_metadata_keys": ["file_name", "file_type", "file_size", "creation_date", "last_modified_date", "last_accessed_date"],
  "excluded_llm_metadata_keys": ["file_name", "file_type", "file_size", "creation_date", "last_modified_date", "last_accessed_date"],
  "relationships": {
    "1": {
      "node_id": "6463d529-c558-498d-b66c-0b282a061c48",
      "node_type": "4",
      "metadata": {
        "file_path": "/app/tmp/code/e996401e-3f8a-4098-8bad-3df4cb88ddbc/apps/backend/app/llm/providers/openai.py",
        "file_name": "openai.py",
        "file_type": "text/x-python",
        "file_size": 2107,
        "creation_date": "2026-02-21",
        "last_modified_date": "2026-02-21",
        "data_source_id": "76797406-12af-411c-81ee-c84da8cf1b30"
      },
      "hash": "a37b9e56e94ba3d1d4d7cff2da6f674c5f60c0cf30b9b31851bbe98459eaeb44",
      "class_name": "RelatedNodeInfo"
    },
    "2": {
      "node_id": "34e86663-88b1-4cdd-811a-a22e3f5a4c15",
      "node_type": "1",
      "metadata": {
        "file_path": "/app/tmp/code/e996401e-3f8a-4098-8bad-3df4cb88ddbc/apps/backend/app/llm/providers/openai.py",
        "file_name": "openai.py",
        "file_type": "text/x-python",
        "file_size": 2107,
        "creation_date": "2026-02-21",
        "last_modified_date": "2026-02-21",
        "data_source_id": "76797406-12af-411c-81ee-c84da8cf1b30"
      },
      "hash": "db84a84f6b85c9f16ec17457df88ec47da60ff654de73ab0b4655d1787225dba",
      "class_name": "RelatedNodeInfo"
    },
    "3": {
      "node_id": "c94688cb-3f7d-42a5-98e5-bab46ba9e35b",
      "node_type": "1",
      "metadata": {},
      "hash": "345bcfec22cf743eedb44e5b159542b5f734105c37f6d3344c8efc25b07492ae",
      "class_name": "RelatedNodeInfo"
    }
  },
  "metadata_template": "{key}: {value}",
  "metadata_separator": "\n",
  "text": "",
  "mimetype": "text/plain",
  "start_char_idx": 187,
  "end_char_idx": 1590,
  "metadata_seperator": "\n",
  "text_template": "{metadata_str}\n\n{content}",
  "class_name": "TextNode"
}
```

**TextNode.metadata**
```json 
{
    "file_path": "/app/tmp/code/e996401e-3f8a-4098-8bad-3df4cb88ddbc/apps/frontend/app/src/components/DataSourcesView.jsx",
    "_node_type": "TextNode",
    "file_name": "DataSourcesView.jsx",
    "doc_id": "8bf1877e-bb93-4260-8042-9fac13e28f33",
    "last_modified_date": "2026-02-21",
    "document_id": "8bf1877e-bb93-4260-8042-9fac13e28f33",
    "data_source_id": "76797406-12af-411c-81ee-c84da8cf1b30",
    "file_size": 17640,
    "ref_doc_id": "8bf1877e-bb93-4260-8042-9fac13e28f33",
    "creation_date": "2026-02-21",
    "_node_content": "..."
},
```


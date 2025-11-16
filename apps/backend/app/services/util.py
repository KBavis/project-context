
def get_normalized_project_name(project_name: str):
    """
    Helper function to get normalized project name, which is used when 
    naming our ChromaDb collections 

    Args:
        project_name (str): project name to normalize 
    """
    return "".join(c.upper() for c in project_name if c.isalnum())

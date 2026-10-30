import os, json

def load_document_metadata(docsdir):
    ## Metadata: { pdfpath: { 'next-page': N, 'log-filename': ..., 'context': ... } }
    metadocs = {}
    for root, dirs, files in os.walk(docsdir, followlinks=True):
        for filename in files:
            fullpath = os.path.join(root, filename)
            if os.path.splitext(filename)[1] == '.pdf':
                if fullpath not in metadocs:
                    metadocs[fullpath] = {}
            elif os.path.splitext(filename)[1] == '.json':
                with open(fullpath, 'r') as fp:
                    metadocs[fullpath.replace(".json", ".pdf")] = json.load(fp)

    return metadocs

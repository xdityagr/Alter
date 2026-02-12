class StreamingJsonParser:
    """
    Parses a stream of JSON tokens from an LLM and extracts the string value 
    associated with the 'content' key.
    """
    def __init__(self):
        # States: 
        # 0: scanning for "content" key
        # 1: scanning for colon after key
        # 2: scanning for opening quote of value
        # 3: inside string value
        self.state = 0
        self.buffer = "" 
        self.escaped = False
        
    def consume(self, chunk: str) -> str:
        out = []
        for char in chunk:
            if self.state == 0:
                self.buffer += char
                # Heuristic: match "content" at end of buffer
                # larger buffer to be safe against newlines/formatting
                if len(self.buffer) > 100:
                    self.buffer = self.buffer[-100:]
                
                if '"content"' in self.buffer:
                    self.state = 1
                    # consume the key from buffer? doesn't matter, we switch state
                    self.buffer = ""
                    
            elif self.state == 1:
                # Expect colon
                if char == ':':
                    self.state = 2
                elif char.strip():
                    # If we encounter non-whitespace char that isn't colon, reset
                    # This might happen if "content" appeared in some other context?
                    # But "content" key should be followed by :
                    self.state = 0
                    self.buffer = char

            elif self.state == 2:
                # Expect opening quote
                if char == '"':
                    self.state = 3
                    self.escaped = False
                elif char.strip():
                    # Invalid JSON if not quote (assuming string value)
                    self.state = 0
                    self.buffer = char

            elif self.state == 3:
                # Inside string
                if self.escaped:
                    # Handle common escapes
                    if char == 'n': out.append('\n')
                    elif char == 't': out.append('\t')
                    elif char == 'r': out.append('\r')
                    elif char == '"': out.append('"')
                    elif char == '\\': out.append('\\')
                    else: 
                        out.append(char) 
                    self.escaped = False
                elif char == '\\':
                    self.escaped = True
                elif char == '"':
                    # End of string
                    self.state = 0
                else:
                    out.append(char)
        
        return "".join(out)

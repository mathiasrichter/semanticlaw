from rdflib import Graph
from pyshacl import validate
import os
import re
import sys
from erdi8 import Erdi8
import cmd2
from pdfminer.high_level import extract_text
from functools import cmp_to_key
import json

class Frame:
    def __init__(
        self,
        id: str,
        line_no: int = None,
        type: str = None,
        parent: str = None,
        prev: str = None,
        next: str = None,
        ord: str = None,
        title: str = None,
        content: str = None,
    ):
        self.id = id
        self.line_no = line_no
        self.type = type
        self.parent = parent
        self.prev = prev
        self.next = next
        self.ord = ord
        self.title = title
        self.content = content
        
    def serialize(self):
        return {
            'id': self.id,
            'line_no': self.line_no,
            'type': self.type,
            'parent': self.parent,
            'prev': self.prev,
            'next': self.next,
            'ord' : self.ord,
            'title' : self.title,
            'content' : self.content
        } 
    
    @classmethod
    def deserialize(self, state:dict):
        f = Frame(state['id'])
        f.line_no = state['line_no']
        f.type = state['type']
        f.parent = state['parent']
        f.prev = state['prev']
        f.next = state['next']
        f.ord = state['ord']
        f.title = state['title']
        f.content = state['content']      
        return f  
        

class StackEmptyError(Exception):
    
    def __init__(self):
        super().__init__("Stack is empty.")
        
class SequenceEmptyError(Exception):
    
    def __init__(self):
        super().__init__("Sequence is empty.")
        

class SequencedStack:
    
    hierarchy = []
    sequence = []

    def append(self, frame:Frame):
        if self.length() > 0:
            prev = self.last()
            frame.prev = prev.id
            prev.next = frame.id
        self.sequence.append(frame)

    def last(self):
        if self.length() == 0:
            raise SequenceEmptyError()
        return self.sequence[self.length()-1]
    
    def push(self, frame:Frame):
        if self.depth() > 0:
            frame.parent = self.top().id
        self.hierarchy.append(frame)
        self.append(frame)
        
    def remove(self):
        if self.depth() > 0:
            self.hierarchy.pop()
            self.sequence.pop()
    
    def pop(self) -> Frame:
        if self.depth() > 0:
            return self.hierarchy.pop()
        raise StackEmptyError()
    
    def top(self) -> Frame:
        if self.depth() > 0:
            return self.hierarchy[-1]
        else:
            return None
            
    def depth(self) -> int:
        return len(self.hierarchy)
    
    def length(self) -> int:
        return len(self.sequence)
    
    def stack_to_string(self) -> str:
        result = ''
        i = 0
        for f in self.hierarchy:
            result += "[" + str(i) + "]" + f.type + ((" " + str(f.ord)) if f.ord is not None else "") + "\n"
            i+=1
        if result == '':
            result = '[empty]'
        else:
            result = result[0:len(result)-2]
        return result

    def sequence_to_string(self, last_count:int = 5) -> str:
        result = ''
        r = range(0, self.length())
        if last_count >= 0 and last_count < self.length():
            r = range(self.length() - last_count, self.length())
        for i in r:
            f = self.sequence[i]
            result += "[" + str(i) + "]" + f.type + ((" " + str(f.ord)) if f.ord is not None else "") + "\n"
            i+=1
        if result == '':
            result = '[empty]'
        else:
            result = result[0:len(result)-2]
        return result

class StructureError(Exception):
    
    def __init__(self, msg:str):
        super().__init__(msg)
        
class TypeError(Exception):
    
    def __init__(self, msg:str):
        super().__init__(msg)
        

class Text:

    text = None
    
    line_no = 0
    
    def __init__(self, pdf_filename:str):
        self.text = extract_text(pdf_filename, 'rb').split('\n')
        
    def next(self):
        self.line_no += 1
        
    def get_line(self):
        return self.text[self.line_no]
        
    def get_lines(self, start:int, end:int):
        if start == end:
            return "".join(self.text[start])
        return self.text[start:end]

class CharacterOrdinal:
    
    def is_valid(self, value:str):
        match = ( re.match('^[a-z]+$', value) is not None )
        if not match:
            return False
        for i in range(0, len(value)-1):
            if value[i] != 'z':
                return False
        return True
    
    def num_ord(self, value:str):
        if self.is_valid(value):
            result = 0
            for i in range(0, len(value)):
                result += ord(value[i])-ord('a')+1
            return result
    
    def next(self, value:str):
        if value == '' or value is None:
            return 'a'
        if self.is_valid(value):
            c = value[len(value)-1]
            if ord(c) < ord('z'):
                result = list(value)
                result[len(value)-1] = chr(ord(c)+1)
                return "".join(result)
            else:
                value += 'a'
            return value
        
    def compare(self, frame1:Frame, frame2:Frame):
        if frame1.ord is None and frame2.ord is not None:
            return -1
        if frame1.ord is not None and frame2.ord is None:
            return 0
        if frame1.ord is None and frame2.ord is None:
            return 1        
        return self.num_ord(frame1.ord) - self.num_ord(frame2.ord)
    
    def sort(self, items : list[Frame]):
        return sorted(items, key=cmp_to_key(self.compare))
        

class Collector(SequencedStack):
    
    BG = "Bundesgesetz"
    BV = "Bundesverordnung"
    KG = "Kantonsgesetz"
    KVO = "Kantonsverordnung"
    KV = "Kantonsverfügung"
    ABSCH = "Abschnitt"
    ART = "Artikel"
    PAR = "Paragraph"
    ABS = "Absatz"
    LIT = "Litera"

    TYPES = [BG, BV, KG, KVO, KV, ABSCH, ART, PAR, ABS, LIT]
    
    TITLE = "title"
    CONT = "cont"
    
    CHAR_ORD = CharacterOrdinal()
    ID = Erdi8()
    
    last_id = None
    text = None    
    cur_mode = None
    cur_start = None
    
    def __init__(self, filename:str):
        self.text = Text(filename)
        start = filename.lower()
        orig = filename.lower()
        for i in range(0,len(orig)):
            if orig[i] not in "23456789abcdefghijkmnopqrstuvwxyz":
                start = start.replace(orig[i], "")
        self.last_id = self.ID.increment(start)
        
    def serialize(self, file_name:str):
        s = []
        for f in self.sequence:
            s.append(f.serialize())
        h = []
        for f in self.hierarchy:
            h.append(f.id)
        state = {
            'last_id': self.last_id,
            'sequence': s,
            'hierarchy': h,
            'text_line_no': self.text.line_no,
            'cur_mode': self.cur_mode,
            'cur_start': self.cur_start
        }
        with open(file_name, 'w') as f:
            json.dump(state, f, indent=4)
        
    def deserialize(self, file_name:str):
        with open(file_name, 'r') as f:
            state = json.load(f)
            self.last_id = state['last_id']
            self.sequence= []
            lookup = {}
            for d in state['sequence']:
                f = Frame.deserialize(d)
                self.sequence.append(f)
                lookup[f.id] = f
            self.hierarchy = []
            for d in state['hierarchy']:
                self.hierarchy.append(lookup[d])
            self.text.line_no = state['text_line_no']
            self.cur_mode = state['cur_mode']
            self.cur_start = state['cur_start']

    def cancel(self):
        if self.top() is not None:
            self.remove()
            if self.top() is not None:
                self.top().next = None        
        self.text.line_no = self.top().line_no if self.top() is not None else 0
        self.cur_mode = None
        self.cur_start = None
        
        
    def next_line(self):
        self.text.next()
        if self.get_line() == '\n' or self.get_line() == '\r' or self.get_line() == '':
            self.next_line()
            
    def next_block(self) -> str:
        self.text.next()
        block = self.get_line()
        while self.get_line() != '\n' and self.get_line() != '\r' and self.get_line() != '':
            self.text.next()
            block += '\n' + self.get_line()
        if self.get_line() == '\n' or self.get_line() == '\r' or self.get_line() == '':
            self.next_line()
        return block
        
    def get_line(self):
        return self.text.get_line()
        
    def get_next_int_ord(self, clazz :str, parent :str) -> int:
        siblings = []
        if clazz in [self.ART, self.PAR]:
            siblings = list(filter(lambda f: True if f.type==clazz and f.ord is not None and type(f.ord) == int else False, self.sequence))
        else:
            siblings = list(filter(lambda f: True if f.type==clazz and f.parent==parent and f.ord is not None and type(f.ord) == int else False, self.sequence))
        siblings.sort(key=lambda x: x.ord)
        if len(siblings) > 0:
            return siblings[-1].ord + 1
        else:
            return 1
        
    def get_next_char_ord(self, clazz :str, parent :str) -> int:
        siblings = list(filter(lambda f: f.type==clazz and f.parent==parent and f.ord is not None and type(f.ord) == str, self.sequence))
        siblings = self.CHAR_ORD.sort(siblings)
        if len(siblings) > 0:
            return self.CHAR_ORD.next(siblings[-1].ord)
        else:
            return 'a'
        
    def is_collecting(self):
        return ( self.cur_start is not None and self.cur_mode is not None)

    def start_collect(self, mode :str):
        if self.is_collecting():
            raise StructureError("Already collecting text.")
        self.cur_mode = mode
        self.cur_start = self.text.line_no    
        
    def end_collect(self) -> str:
        if not self.is_collecting():
            raise StructureError("Not currently collecting text.")
        result = self.get_collect_content()
        self.cur_start = None
        return result
    
    def get_collect_content(self):
        if self.is_collecting():
            return "\n".join(self.text.get_lines(self.cur_start, self.text.line_no))
        return ""

    def new_id(self):
        self.last_id = self.ID.increment(self.last_id)
        return self.last_id
    
    def new_document(self, type:str):
        if self.depth() > 0:
            raise StructureError("New dcoument cannot be opened within an existing scope.")
        if type not in self.TYPES:
            raise TypeError("Unkown document type '{}'".format(type))
        self.push(Frame(self.new_id(), line_no=self.text.line_no, type=type))
        
    def new_title(self):
        if self.top() and self.top().type in [self.ABS, self.LIT, self.TITLE, self.CONT]:
            raise StructureError("Cannot open title scope in {}".format(self.top().type))
        self.start_collect(self.TITLE)

    def new_content(self):
        if self.top() and self.top().type in [self.ABSCH, self.TITLE, self.CONT]:
            raise StructureError("Cannot open content scope in {}".format(self.top().type))
        self.start_collect(self.CONT)
    
    def new_abschnitt(self):
        if self.top() and self.top().type in [self.TITLE, self.CONT, self.ART, self.PAR, self.ABS, self.LIT]:
            raise StructureError("Cannot open abschnitt scope in {}".format(self.top().type))
        f = Frame(self.new_id(), line_no=self.text.line_no, type=self.ABSCH)
        self.push(f)
        f.ord = self.get_next_int_ord(self.ABSCH, f.parent)
        
    def new_article(self):
        if self.top() and self.top().type in [self.TITLE, self.CONT, self.ART, self.PAR, self.ABS, self.LIT]:
            raise StructureError("Cannot open article scope in {}".format(self.top().type))
        f = Frame(self.new_id(), line_no=self.text.line_no, type=self.ART)
        self.push(f)
        f.ord = self.get_next_int_ord(self.ART, f.parent)
        
    def new_paragraph(self):
        if self.top() and self.top().type in [self.TITLE, self.CONT, self.ART, self.PAR, self.ABS, self.LIT]:
            raise StructureError("Cannot open paragraph scope in {}".format(self.top().type))
        f = Frame(self.new_id(), line_no=self.text.line_no, type=self.PAR)
        self.push(f)
        f.ord = self.get_next_int_ord(self.PAR, f.parent)

    def new_absatz(self):
        if self.top() and self.top().type in [self.TITLE, self.CONT, self.ABS, self.LIT, self.BG, self.BV, self.KG, self.KV, self.KVO]:
            raise StructureError("Cannot open absatz scope in {}".format(self.top().type))
        f = Frame(self.new_id(), line_no=self.text.line_no, type=self.ABS)
        self.push(f)
        f.ord = self.get_next_int_ord(self.ABS, f.parent)

    def new_litera(self):
        if self.top() and self.top().type in [self.TITLE, self.CONT, self.BG, self.BV, self.KG, self.KV, self.KVO]:
            raise StructureError("Cannot open litera scope in {}".format(self.top().type))
        f = Frame(self.new_id(), line_no=self.text.line_no, type=self.LIT)
        self.push(f)
        f.ord = self.get_next_char_ord(self.LIT, f.parent)

    def end(self):
        cur = self.top()
        if self.is_collecting():
            if self.cur_mode == self.TITLE:
                cur.title = self.end_collect()
            elif self.cur_mode == self.CONT:
                cur.content = self.end_collect()
            else:
                raise StructureError("Unknown collection mode.")
        else:
            self.pop()
            
    def build_graph(self) -> Graph:
        graph = Graph()
        prefix  = "PREFIX : <http://example.org/> "
        prefix += "PREFIX sl: <https://raw.githubusercontent.com/mathiasrichter/semanticlaw/main/swisslaw.ttl#> "
        for f in self.sequence:
            query = prefix + "INSERT DATA { "
            query += ":" + f.id + " a sl:" + f.type + " . "
            if f.parent is not None:
                query += ":" + f.id + " sl:parent :" + f.parent + " . "
            if f.prev is not None:
                query += ":" + f.id + " sl:prev :" + f.prev + " . "
            if f.next is not None:
                query += ":" + f.id + " sl:next :" + f.next + " . "
            if f.title is not None:
                query += ":" + f.id + ' sl:title """' + f.title + '"""@de . '
            if f.content is not None:
                query += ":" + f.id + ' sl:content """' + f.content + '"""@de . '
            if f.ord is not None:
                if type(f.ord) == int:
                    query += ":" + f.id + " sl:ord " + str(f.ord) + " . "
                else:
                    query += ":" + f.id + ' sl:ord "' + f.ord + '" . '
            query += "}"
            graph.update(query)
        return graph
        
        
    def save(self, file_name:str):
        with open(file_name, "w") as f:
            f.writelines(self.build_graph().serialize(format='ttl'))


class CommandlineCollector(cmd2.Cmd):

    def __init__(self, filename:str):
        super().__init__()
        self.prompt = '>'
        self.collector = Collector(filename)
        self.print_status()
        
    def do_new(self, line:str):
        if line.lower() == self.collector.BG.lower():
            self.collector.new_document(line)
        elif line.lower() == self.collector.BV.lower():
            self.collector.new_document(line)
        elif line.lower() == self.collector.KG.lower():
            self.collector.new_document(line)
        elif line.lower() == self.collector.KV.lower():
            self.collector.new_document(line)
        elif line.lower() == self.collector.KVO.lower():
            self.collector.new_document(line)
        elif self.collector.ABSCH.lower().startswith(line.lower()):
            self.collector.new_abschnitt()
        elif self.collector.ABS.lower().startswith(line.lower()):
            self.collector.new_absatz()
        elif self.collector.PAR.lower().startswith(line.lower()):
            self.collector.new_paragraph()
        elif self.collector.ART.lower().startswith(line.lower()):
            self.collector.new_article()
        elif self.collector.LIT.lower().startswith(line.lower()):
            self.collector.new_litera()
        else:
            print("Unknown type:",line)
        self.print_status()

    def do_end(self, line):
        self.collector.end()
        self.print_status()
        
    def print_status(self):
        frame = self.collector.top()
        pos = '-'
        if frame is not None:
            pos = frame.type + ( (" " + str(frame.ord)) if frame.ord is not None else "")
            if self.collector.is_collecting():
                pos += ' ' + self.collector.cur_mode
        print('['+ str(self.collector.text.line_no)+'/'+ str(len(self.collector.text.text)-1) + ' ' + pos + '] ' + self.collector.get_line())
        
    def do_title(self, line:str):
        self.collector.new_title()
        self.print_status()
        
    def do_content(self, line:str):
        self.collector.new_content()
        self.print_status()
        
    def do_next(self, line:str):
        self.collector.next_line()
        self.print_status()
        
    def do_block(self, line:str):
        print(self.collector.next_block())
        self.print_status()
        
    def do_line(self, line:str):
        self.print_status()
        
    def do_show(self, line:str):
        print(self.collector.get_collect_content())
        self.print_status()
        
    def do_save(self, line:str):
        self.collector.save(line)
        self.print_status()
        
    def do_stack(self, line:str):
        print(self.collector.stack_to_string())
        self.print_status()
        
    def do_seq(self, line:str):
        if line.isdigit():
            print(self.collector.sequence_to_string(int(line)))
        else:
            print(self.collector.sequence_to_string())
        self.print_status()
        
    def do_cancel(self, line:str):
        self.collector.cancel()
        self.print_status()
        
    def do_savestate(self, line:str):
        self.collector.serialize(line)
        self.print_status()

    def do_restorestate(self, line:str):
        self.collector.deserialize(line)
        self.print_status()

if __name__ == "__main__":
    if len(sys.argv) <= 1 or len(sys.argv) > 2:
        print("filename required")
        exit()
    filename = sys.argv[1]
    sys.argv = [sys.argv[0]]
    app = CommandlineCollector(filename)
    app.cmdloop()

from rdflib import Graph
from pyshacl import validate
import os
import re
from erdi8 import Erdi8
import cmd2

ERDI = Erdi8()

class State:
    
    ROMAN_ORD = "roman"
    INT_ORD = "int"
        
    BG = "Bundesgesetz"
    BV = "Bundesverordnung"
    KG = "Kantonsgesetz"
    KVO = "Kantonsverordnung"
    KV ="Kantonsverfügung"
    ABSCH = "Abschnitt"
    ART = "Artikel"
    PAR = "Paragraph"
    ABS = "Absatz"
    LIT = "Litera"
    
    CLASSES = [BG, BV, KG, KVO, KV, ABSCH, ART, PAR, ABS, LIT]
    
    def __init__(self, tmp_file_name :str = "tmp.ttl" ):
        self.graph = Graph()
        self.tmp_file_name = tmp_file_name
        self.init()
        
    def init(self):
        self.text = ""
        self.namespace = "http://example.org/"
        self.cur_class = None
        self.cur_id = None
        self.cur_parent = None
        self.cur_prev = None
        self.cur_next = None
        self.cur_ord = None
        self.cur_title = None
        self.cur_content = None
        self.dirty = False
        self.saved = True
        
    def namespace(self, namespace : str ):
        self.namespace = namespace

    def load(self, file_name:str):
        with open(self.file_name, "r") as f:
            self.text = f.readlines()
        self.graph = Graph().parse(file_name)
      
    def save(self, file_name:str):
        with open(file_name, "w") as f:
            self.text = f.writelines(self.text)
        self.saved = True
        
    def update_graph(self):
        with open(self.tmp_file_name, "w") as f:
            f.writelines(self.text)
        g = Graph().parse(self.tmp_file_name)
        self.graph = g
        os.remove(self.tmp_file_name)
        return None

    def commit(self):
        if self.dirty is True:
            s = 'PREFIX : <' + self.namespace + '> .\n\n'
            s += ':' + self.cur_id + ' a :' + self.cur_class if self.cur_class is not None else '' + ' ;\n'
            if self.cur_parent is not None:
                s += '\t:parent ' + self.cur_parent + ' ;\n\n' 
            if self.cur_prev is not None:
                 s += '\t:prev ' + self.cur_prev + ' ;\n\n' 
            if self.cur_next is not None:
                 s += '\t:next ' + self.cur_next + ' ;\n\n' 
            if self.cur_ord is not None:
                 s += '\t:ord "' + self.cur_ord + '" ;\n\n' 
            if self.cur_title is not None:
                 s += ':title """' + self.cur_title + '""""@de ;\n\n'
            if self.cur_content is not None:
                 s += ':content """' + self.cur_content + '""""@de ;\n\n\n'
            s += '.'
            self.text += s
            self.update_graph()
            self.dirty = False
        
        
    def up(self):
        if self.cur_parent is not None:
            self.set(self.cur_parent)
    
    def down(self, isArtikel:bool, ord_type:str):
        self.cur_next = ERDI.increment(self.cur_id)
        self.commit()
        self.dirty = True
        self.saved = False
        self.cur_parent = self.cur_id
        self.cur_id = self.cur_next
        self.cur_prev = self.parent
        self.cur_next = None
        self.cur_title = None
        self.cur_content = None
        if self.cur_class in [self.BG, self.BV, self.KG, self.KVO, self.KV]:
            self.cur_class = self.ABSCH
            self.cur_ord = 1             
        elif self.cur_class == self.ABSCH:
            if isArtikel == True:
                self.cur_class = self.ART
            else:
                self.cur_class = self.PAR
            if ord_type == self.INT_ORD:
                self.cur_ord = 1
            elif ord_type == self.ROMAN_ORD:
                self.cur_ord = "I"
        elif self.cur_class == self.ART:
            self.cur_class = self.ABS
            self.cur_ord = 1             
        elif self.cur_class == self.PAR:
            self.cur_class = self.ABS
            self.cur_ord = 1             
        elif self.cur_class == self.ABS:
            self.cur_class = self.LIT
            self.cur_ord = 1             
        elif self.cur_class == self.LIT:
            pass # no further hierarchy level below lit
    
    def next(self):
        self.cur_next = ERDI.increment(self.cur_id)
        self.commit()
        self.dirty = True
        self.saved = False
        self.cur_id = self.cur_next
        self.cur_prev = self.cur_id
        self.cur_next = None
        if self.cur_ord is not None:
            if type(self.cur_ord) == int:
                self.cur_ord += 1
            else:
                self.cur_ord = chr((ord(self.cur_ord)+1 - 65) % 26 + 65)
        self.cur_title = None
        self.cur_content = None
    
    def prev(self):
        if self.cur_prev is not None:
            self.set(self.cur_prev)
            
    def set_title(self, title:str):
        self.cur_title = title
        self.dirty = True
    
    def set_content(self, content:str):
        self.cur_content = content
        self.dirty = True

    def set(self, id :str):
        query = """
                SELECT DISTINCT ?predicate ?object
                WHERE
                {
                    ?element ?predicate ?object .
                    FILTER(STRENDS(STR(?element), """+ id +""")) .
                }
        """
        result = self.graph.query(query)
        self.init()
        self.cur_id = id
        for r in result:
            if str(r.predicate).endswith("type"):
                self.cur_class = self.extract_id(str(r.object))
            if str(r.predicate).endswith("prev"):
                self.cur_prev = self.extract_id(str(r.object))
            if str(r.predicate).endswith("next"):
                self.cur_next = self.extract_id(str(r.object))
            if str(r.predicate).endswith("parent"):
                self.cur_parent = self.extract_id(str(r.object))
            if str(r.predicate).endswith("title"):
                self.cur_title = self.extract_id(str(r.object))
            if str(r.predicate).endswith("content"):
                self.cur_content = self.extract_id(str(r.object))
            if str(r.predicate).endswith("ord"):
                s = self.extract_id(str(r.object))
                if s.isdigit() == True:
                    self.cur_ord = int(s)
    
    def start(self, clazz:str):
        self.init()
        self.cur_class = clazz
        self.cur_id = ERDI.increment(clazz.lower())
        self.dirty = True
        
      
    def to_string(self):
        s = """
------------------------------------------
Type:      {}
Id:        {}
Parent:    {}
Prev:      {}
Next:      {}
Title:     {}
Content:   {}
Ord:       {}
------------------------------------------
        """
        return s.format( 
            (':'+self.cur_class) if self.cur_class is not None else '',
            (':'+self.cur_id) if self.cur_id is not None else '',
            (':'+self.cur_parent) if self.cur_parent is not None else '',
            (':'+self.cur_prev) if self.cur_prev is not None else '',
            (':'+self.cur_next) if self.cur_next is not None else '',
            (self.cur_title[0:10]+"...") if self.cur_title is not None else '',
            (self.cur_content[0:20]+"...") if self.cur_content is not None else '',
            self.cur_ord if self.cur_ord is not None else ''
        )

class Collector(cmd2.Cmd):
    
    state = State()
    
    def __init__(self,):
        super().__init__(multiline_commands=['title', 'content'])
    
    def do_start(self, line:str ):
        if line in self.state.CLASSES:
            self.state.start(line)
        print(self.state.to_string())
        
    def do_status(self, line:str):
        print(self.state.to_string())
        
    def do_title(self, line:str):
        self.state.set_title(line)
        
    def do_content(self, line:str):
        self.state.set_content(line)

    def do_load(self, line:str):
        self.state.load(line)
        
    def do_save(self, line:str):
        self.state.save(line)
        
    def do_commit(self, line:str):
        self.state.commit()
        
    def do_showtext(self, line:str):
        print(self.state.text)
        
    def do_exit(self, line:str):
        if self.state.dirty == True:
            print("You have uncommitted changes. Either commit or use 'forcequit' to exit without committing.")
            return
        if self.state.saved == False:
            print("You have unsaved changes. Either save or use 'forcequit' to exit without committing.")
            return
        exit() 
        
    def do_forcequit(self, line:str):
        exit() 

  
if __name__ == '__main__':
    app = Collector()
    app.use_rawinput = True
    app.cmdloop()
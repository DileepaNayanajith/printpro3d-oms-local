"""Home staff pairing wizard. Network validation never claims a print job."""
import json
import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from home_worker import station_root
from oms.station_client import API, save


def main():
    root=station_root();root.mkdir(parents=True,exist_ok=True)
    settings=root/'settings.json'
    old=json.loads(settings.read_text()) if settings.exists() else {}
    app=tk.Tk();app.title('PRINTPRO3D - Connect home PC');app.geometry('650x550')
    frame=ttk.Frame(app,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Connect your home PC',font=('Segoe UI',20,'bold')).pack(anchor='w')
    ttk.Label(frame,text='You can install now and connect later when the online OMS address is ready.',wraplength=590).pack(anchor='w',pady=(8,16))
    values={key:tk.StringVar(value=old.get(key,'')) for key in ('url','token','printer','sumatra')}
    for key,label in [('url','Online OMS address (https://...)'),('token','Pairing key from Owner > Home PC')]:
        ttk.Label(frame,text=label).pack(anchor='w');ttk.Entry(frame,textvariable=values[key],show='*' if key=='token' else '').pack(fill='x',pady=(3,12))
    candidates=[Path(os.environ.get('ProgramFiles','C:/Program Files'))/'SumatraPDF/SumatraPDF.exe',Path(os.environ.get('LOCALAPPDATA',''))/'SumatraPDF/SumatraPDF.exe']
    if not values['sumatra'].get():values['sumatra'].set(str(next((p for p in candidates if p.is_file()),'')))
    ttk.Label(frame,text='SumatraPDF program').pack(anchor='w')
    row=ttk.Frame(frame);row.pack(fill='x',pady=(3,12));ttk.Entry(row,textvariable=values['sumatra']).pack(side='left',fill='x',expand=True)
    def browse():
        path=filedialog.askopenfilename(filetypes=[('SumatraPDF','*.exe')])
        if path:values['sumatra'].set(path)
    ttk.Button(row,text='Browse',command=browse).pack(side='right')
    printers=subprocess.run(['powershell','-NoProfile','-Command','Get-Printer | Select-Object -ExpandProperty Name'],capture_output=True,text=True).stdout.splitlines()
    ttk.Label(frame,text='HP printer (install its Windows driver first)').pack(anchor='w')
    ttk.Combobox(frame,textvariable=values['printer'],values=printers,state='readonly').pack(fill='x',pady=(3,12))
    status=tk.StringVar(value='Printer preferences: A4 / Landscape / one page per sheet / single-sided.')
    ttk.Label(frame,textvariable=status,wraplength=590).pack(anchor='w',pady=8)
    def finish(error=None):
        button.config(state='normal')
        if error:status.set(error);return
        messagebox.showinfo('Connected','PC paired successfully. Open PRINTPRO3D Start, then log in to FDE and WhatsApp.');app.destroy()
    def connect():
        data={k:v.get().strip() for k,v in values.items()}
        if not Path(data['sumatra']).is_file() or data['printer'] not in printers:
            status.set('Choose SumatraPDF and a printer from the list.');return
        if not data['token']:status.set('Enter the pairing key from the online OMS.');return
        try:api=API(data['url'],data['token'])
        except ValueError as exc:status.set(str(exc));return
        button.config(state='disabled');status.set('Checking the online connection…')
        def check():
            try:
                api.post('poll',{'kind':'print','ready':False});save(settings,data)
            except Exception:
                app.after(0,lambda:finish('Could not connect. Check internet, OMS address and pairing key. Nothing was changed.'))
            else:app.after(0,finish)
        threading.Thread(target=check,daemon=True).start()
    button=ttk.Button(frame,text='Connect PC',command=connect);button.pack(fill='x',pady=8)
    ttk.Button(frame,text='Connect later',command=app.destroy).pack()
    app.mainloop()

if __name__=='__main__':main()

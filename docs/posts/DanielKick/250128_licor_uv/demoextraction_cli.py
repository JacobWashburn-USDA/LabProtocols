#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
# "pandas",
# "openpyxl",
# ]
# ///

import os, re, argparse
import pandas as pd

def parse_licor(
    fp:str # file path
    ) -> dict:
    """Accept a file path to a licor text file. This file contains a header followed by tablular data. Return a dict of all subtables."""

    with open(fp, 'r') as f:
        dat = f.readlines()
    # Find what row the data tag is on
    data_i = [i for i in range(len(dat)) if dat[i] == '[Data]\n'][0]
    # Process Header ----
    # Separate out the header
    header = [dat[i] for i in range(len(dat)) if i < data_i][1:]
    # find sub-tables of the header
    re_header_idx = lambda x: [i for i in range(len(header)) if re.match(x, header[i])]
    header_parts = {e:re_header_idx(r'^'+e) for e in ['LQConst', 'LTConst', 'LeakConst', 'QConst', 'SysConst']}
    _ = sum([header_parts[e] for e in header_parts], [])
    header_parts['Header'] = [i for i in range(len(header_parts)) if i not in _]

    # Get each sub-table's rows, convert to table
    out = {}
    for part in list(header_parts.keys()):
        #TODO change lc to something more friendly. lc is for LeakConst
        lc = [header[i].replace(f'{part}:', '').strip('\n').split('\t') for i in header_parts[part]]
        # header can contain single values with spaces, otherwise spaces indicate a list

        if part == 'Header':
            lc = {e[0]:e[1] for e in lc}

        else:
            lc = {e[0]:e[1] if ' ' not in e[1] else e[1].split(' ') for e in lc}
        # check if there needs to be an index passed
        if max([len(lc[e]) if type(lc[e]) in [list, tuple] else 1 for e in lc]) == 1:
            # pass index if all scalars
            lc = pd.DataFrame(lc, index=[0])
        else:
            lc = pd.DataFrame(lc)
        out[part] = lc

    # process data ----
    data = [dat[i] for i in range(len(dat)) if i > data_i]
    # header information is over three rows. We need at least the first two to make the cols unique.
    data_headers = [f'{group}__{name}__({unit})' for group, name, unit in zip(
        data[0].strip('\n').split('\t'),
        data[1].strip('\n').split('\t'),
        data[2].strip('\n').split('\t'))]
    data = [data[i] for i in range(len(data)) if i not in [0, 1, 2]] # remove header info
    data = pd.DataFrame(data=[e.strip('\n').split('\t') for e in data[1:]], columns = data_headers )
    out['Data'] = data

    # Add in identifier (name)
    out = {k:out[k].assign(FileName = fp.split('/')[-1]) for k in out}

    return out


def licor_to_tables(
    inp_dir:str, # directory containing licor txt files as the only files without an extension
    out_dir:str,  # directory containing the output tables
    ignore_files:list = [], # list of iles to ignore
    ) -> None:

    # NOTE ideally there would be a schema provided for each table
    #licor text files don't have a file extension
    licor_txts = [e for e in os.listdir(inp_dir) if not re.findall(r'\.', e)]
    licor_txts = [e for e in licor_txts if e not in ignore_files]
    licor_path = f"{out_dir}{'/' if out_dir[-1] != '/' else ''}LICOR.xlsx"

    for licor_txt in licor_txts:
        file_path = f'{inp_dir}{licor_txt}'
        print(f'Beginning:{file_path}')
        out = parse_licor(file_path)
        # diallow the empty column
        out = {k:[out[k].drop(columns = ['____()']) if '____()' in out[k].columns else out[k]][0] for k in out.keys()}

        if not os.path.exists(licor_path):
            with pd.ExcelWriter(licor_path, mode='w') as writer:
                for k in out.keys():    
                    out[k].to_excel(writer, sheet_name = k, index = False)
        else:
            # if there is a file already try to retrieve the relevant sheet and append to it. 
            # Tyler/Emma, I leave it to you to enforce data types in this file. 
            for k in out.keys():    
                try: 
                    current_data = pd.read_excel(licor_path, sheet_name=k)
                    out[k] = pd.concat([current_data, out[k]])
                    del current_data
                except ValueError:
                    pass

            with pd.ExcelWriter(licor_path, mode='a', if_sheet_exists = 'replace') as writer:
                out[k].to_excel(writer, sheet_name = k, index = False)
            
    print('Running Deduplication')
    keys = ['LQConst', 'LTConst', 'LeakConst', 'QConst', 'SysConst', 'Header', 'Data']
    for k in keys:
        current_data = pd.read_excel(licor_path, sheet_name=k).drop_duplicates() 
        with pd.ExcelWriter(licor_path, mode='a', if_sheet_exists = 'replace') as writer:
            current_data.to_excel(writer, sheet_name = k, index = False)



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--inp_dir",      type=str, help="path to new LICOR text files.")
    parser.add_argument("--out_dir",      type=str, help="path to output tables.")
    parser.add_argument("--ignore_files", type=str, nargs='*', action='append', help="(Optional) names of the files that should be ignored separated by a space.")
    args = parser.parse_args()

    inp_dir = args.inp_dir if args.inp_dir != None else './'
    out_dir = args.out_dir if args.out_dir != None else './'

    def as_lat(inp):
        lat = lambda x: True if list not in [type(e) for e in x] else False
        while lat(inp) != True:
            # turn everything that isn't a list into one, then use sum to concat the lists
            inp = sum([[e] if type(e) != list else e for e in inp], [])
        return inp
        
    ignore_files = as_lat(args.ignore_files) if args.ignore_files != None else []

    # Remove any files that have multiple headers.
    pths = [inp_dir+e for e in os.listdir(inp_dir) if '.' not in e]
    def count_headers(pth):
        with open(pth, 'r') as f:
            dat = f.readlines()
        return(len([e for e in dat if e=='[Header]\n']))

    pths = [pth for pth in pths if count_headers(pth) != 1]

    if pths != []:
        print('The following files have multiple headers and will be ignored:')
        print('\n'.join(pths))
        print('\n')
        ignore_files = list(set(ignore_files+pths))


    licor_to_tables(
        inp_dir=inp_dir,
        out_dir=out_dir, 
        ignore_files = ignore_files
        )



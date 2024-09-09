#! /home/kickd/micromamba/envs/apsimxml/bin/python
num_parquets = 2 # How many should be processed in this batch? 
                 # 0 will try to process all of them.

import tqdm
# reading parquet
import os, json, re, datetime
# import pyarrow as pa
import pyarrow.parquet as pq
# writing to psql
import pandas as pd
import psycopg2
from   sqlalchemy import create_engine, text

# Connect to database
with open('./psql_details.json', 'r') as f:
    d = json.load(f)
    
engine = create_engine(
        f"postgresql+psycopg2://{d['user']}:{d['pass']}@{d['host']}:{d['port']}/{d['name']}", 
        # echo=True
        echo=False
        )

# How to get a result:

# with engine.connect() as conn:
#     Other attempts
#     # result = conn.execute(text('SELECT * FROM public.Ids LIMIT 10;'))
#     # result = conn.execute(text('SELECT * FROM "Ids" LIMIT 10;'))
#     result = conn.execute(text('SELECT * FROM public.ids LIMIT 1'))

# Identify files to add
parquet_path = '/path/to/parquet_files/'

# constrain to the parquets that exist in the path
existing_parquet = [e for e in os.listdir(parquet_path) if re.match('sim_\d+_\d+\.parquet', e)]

with engine.connect() as conn:
    existing_tables = pd.read_sql(sql=text('SELECT * FROM pg_tables;'), con=conn) 
    existing_tables = existing_tables.tablename.tolist() 

if 'ids' not in existing_tables:
    ids = pq.read_table(parquet_path+'Ids.parquet').to_pandas()
    ids.loc[(ids.File.isin(existing_parquet)), ].reset_index()
    # clean up names
    ids = pq.read_table(parquet_path+'Ids.parquet').to_pandas()
    ids = ids.rename(columns={e:e.lower().replace('.', '_') for e in list(ids)})
    ids = ids.loc[:, ['file', 'genotype', 'factorialuid',
                      'longitude', 'latitude', 'soilidx', 'sowdate']]
    ids.to_sql(name='ids', con=engine, if_exists = 'append',  schema='public')


if 'genotypes' not in existing_tables:
    genotypes = pq.read_table(parquet_path+'Genotypes.parquet').to_pandas()
    genotypes.loc[(genotypes.File.isin(existing_parquet)), ].reset_index()
    # clean up names
    genotypes = genotypes.rename(columns={e:e.lower().replace('.', '_') for e in list(genotypes)})
    # overwrite none with NaN (only applies to the calibrated values)
    for e in [e for e in list(genotypes) if not e in ['file','genotype']]:
        genotypes[e] = genotypes[e].astype(float)

    genotypes.to_sql(name='genotypes', con=engine, if_exists = 'append',  schema='public')


# Setup ref for date lookup
start = datetime.datetime.strptime('1970-1-1', '%Y-%m-%d').date()
date_lookup = pd.DataFrame(
    [(i, (start + datetime.timedelta(days=i)) ) for i in range(20089)], # 20089 is days to 2050
     columns=['Date', 'RealDate']
)


finished_parquet = [] 
if os.path.exists('./finished_parquet.json'):
    with open('./finished_parquet.json', 'r') as f:
        finished_parquet = json.load(f)

existing_parquet = [e for e in existing_parquet if e not in finished_parquet]

if num_parquets == 0:
    num_parquets = len(existing_parquet)

for e in existing_parquet[0:num_parquets]: 
    # so that we can run this process in parallel we'll track which files have been reserved
    reserved_parquet = []
    if os.path.exists('./reserved_parquet.json'):
        with open('./reserved_parquet.json', 'r') as f:
            reserved_parquet = json.load(f)
    if e in reserved_parquet:
        pass
    else:
        # log that this entry reserved
        reserved_parquet.append(e)
        with open('./reserved_parquet.json', 'w') as f:
            json.dump(reserved_parquet, f)
        # 

        ## load data ====
        results = pq.read_table(parquet_path+e).to_pandas()

        # add in real dates
        results = results.merge(date_lookup)
        results = results.drop(columns=['Date']).rename(columns = {'RealDate':'Date'})

        # clip "parquet" if it exists and write in
        results['File'] = (lambda x: x[:-8] if x[-8:] == '.parquet' else x)(e)
        results = results.loc[:, ['File', 'FactorialUID', 'Date', 
                                'Maize.AboveGround.Wt', 'Maize.LAI','yield_Kgha']]
        # clean up names
        results = results.rename(columns={e:e.lower().replace('.', '_') for e in list(results)})
    
        print(f'Processing {e}')

        # These files are big enought to cause problems (timeout?) to fix this
        # we append _many_ times
        # results.to_sql(name='results', con=engine, if_exists = 'append',  schema='public')
        #                      __...    
        max_rows_per_append = 1000000 

        max_val = results.index.max()
        blocks = [i for i in range(0, max_val, max_rows_per_append)]+[max_val]
        # deduplicate in case the last step is the max value
        blocks = sorted(list(set(blocks)))
        blocks = [(i,j) for i,j in zip(blocks[0:-1], blocks[1:])]

        for block in tqdm.tqdm(blocks):
            results[block[0]:block[1]].to_sql(name='results', con=engine, if_exists = 'append',  schema='public')

        # After completion, log that the file has been processed
        finished_parquet.append(e)
        with open('./finished_parquet.json', 'w') as f:
            json.dump(finished_parquet, f)
        print('\n')

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# 
#   Licensed under the Apache License, Version 2.0 (the "License").
#   You may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#  
#       http://www.apache.org/licenses/LICENSE-2.0
#  
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import argparse
import torch
from torch.utils.data import TensorDataset
import torch.nn.functional as F
import torch
from transformers import BertModel, BertTokenizer
from torch.utils.data import DataLoader, SequentialSampler
from tqdm import tqdm
import numpy as np
import pandas as pd

def generate_dataset(X, tokenizer, pad_to_max_length=True, add_special_tokens=True, max_length=256, return_attention_mask=True, return_tensors='pt'):
    tokens_query = tokenizer.batch_encode_plus(
        X, 
        pad_to_max_length=pad_to_max_length,
        add_special_tokens=add_special_tokens,
        max_length=max_length,
        return_attention_mask=return_attention_mask, # 0: padded tokens, 1: not padded tokens; taking into account the sequence length
        return_tensors=return_tensors,
    )
    dataset = TensorDataset(
        tokens_query['input_ids'], 
        tokens_query['attention_mask'], 
        tokens_query['token_type_ids'],
    )
    # 0: query_inputs_ids, 1 : query_attention_mask, 2 : query_token_type_ids, 3
    return dataset

def pool_summary(last_hidden_states, pool_summary_op="max"):
    num_features = last_hidden_states.size()[1]
    last_hidden_states_p = last_hidden_states.permute(0, 2, 1) # [batch_size, length, num_features] -> [batch_size, num_features, length]
    func_pool_summmary = F.max_pool1d if pool_summary_op == "max" else F.avg_pool1d
    return func_pool_summmary(last_hidden_states_p, kernel_size=num_features).squeeze(-1) # [batch_size, num_features]

def inference(model, dataloader, list_ids, device="cuda:0"):
    d = {}
    i = 0
    model.to(device)
    for dataloader_batch in tqdm(dataloader):
        # 0: inputs_ids, 1: attention_mask, 2: token_type_ids, 3: ids
        inputs = {
            'input_ids': dataloader_batch[0].to(device),
            'attention_mask': dataloader_batch[1].to(device),
            'token_type_ids': dataloader_batch[2].to(device),
        }
        batch_size = dataloader_batch[0].shape[0]
        list_ids_ = list_ids[i:i+batch_size]
        with torch.no_grad():
            output_ = pool_summary(model(**inputs)[0]).detach().cpu().numpy()
            for (j, id_) in enumerate(list_ids_):
                d[id_] = output_[j]
        i = i + batch_size
    return d

def compute_bert_representations(input_file, output_file, col_id, col_text, tokenizer, model, max_length=256, batch_size=128, device="cuda:0"):
    df = pd.read_csv(input_file)
    df.fillna('', inplace=True)
    if col_id not in df:
        df[col_id] = df[col_text].to_list()
    df = df[[
        col_id,
        col_text,
    ]]
    df = df.drop_duplicates(subset=[col_id],  keep='first')
    dataset = generate_dataset(
        df[col_text].to_list(),
        tokenizer, 
        max_length=max_length,
    )
    sampler = SequentialSampler(dataset)
    dataloader = DataLoader(dataset, sampler=sampler, batch_size=batch_size)
    dict = inference(
        model,
        dataloader,
        df[col_id].to_list(),
        device=device,
    )
    np.save(output_file, dict)


def main():
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_queries_path_file", type=str, default=None, help="Input CSV with the query information.")
    parser.add_argument("--output_queries_path_file", type=str, default=None, help="Output file with the mapping of the queries to BERT representations.")
    parser.add_argument("--input_product_catalogue_path_file", type=str, default=None, help="Input CSV with the product information.")
    parser.add_argument("--output_product_catalogue_path_file", type=str, default=None, help="Output file with the mapping of the queries to BERT representations.")
    parser.add_argument("--model_name", type=str, default="bert-base-multilingual-uncased", help="BERT multilingual model name.")
    parser.add_argument("--bert_max_length", type=int, default=256, help="Tokens consumed by BERT (512 tokens max).")
    parser.add_argument("--batch_size", type=int, default=128, help="Batch size.")
    args = parser.parse_args()

    """ 1. Load models"""
    model = BertModel.from_pretrained(args.model_name)
    tokenizer = BertTokenizer.from_pretrained(args.model_name)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    """ 2. Encode products"""
    col_product_id = "product_id" 
    col_product_title = "product_title"
    if args.input_product_catalogue_path_file and args.output_product_catalogue_path_file:
        compute_bert_representations(
            args.input_product_catalogue_path_file, 
            args.output_product_catalogue_path_file, 
            col_product_id, 
            col_product_title, 
            tokenizer, 
            model, 
            max_length=args.bert_max_length, 
            batch_size=args.batch_size,
            device=device,
        )
    
    """ 3. Encode queries """
    col_query_id = "query_id"
    col_query = "query"
    if args.input_queries_path_file and args.output_queries_path_file:
        compute_bert_representations(
            args.input_queries_path_file, 
            args.output_queries_path_file, 
            col_query_id, 
            col_query, 
            tokenizer, 
            model, 
            max_length=args.bert_max_length, 
            batch_size=args.batch_size,
            device=device,
        )


if __name__ == "__main__": 
    main()  
import os
import argparse
import torch
import torch.nn as nn
from torch.nn import functional as F

# %%%%%%%%%%%%%
# Args
# %%%%%%%%%%%%%
parser = argparse.ArgumentParser(description='tinyGPT')
parser.add_argument('-f','--file', help='Input training file', required=True)
parser.add_argument('-i','--max_iters', help='Iterations for learning', required=False)
parser.add_argument('-g','--generate', help='Generate text based on a pre-trained model', required=False)
args = vars(parser.parse_args())

filename = args['file']
SAVE_PATH = "models/model"

# ----------------
# hyperparameters
batch_size = 64 # how many independent sequences will we process in parallel
block_size = 256 # what is the maximum context length for predictions
max_iters = int(args['max_iters']) if args['max_iters'] else 5000
eval_interval = max_iters//10
learning_rate = 3e-4
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f'Defaulting device to {device}')
eval_iters = 200
n_embd = 384
n_heads = 3
n_layer = 3 # how many resBlocks to create
dropout = 0.2
# ----------------

torch.manual_seed(1337)

with open(filename, 'r', encoding='utf-8') as f:
    text = f.read()

chars = sorted(list(set(text)))
vocab_size = len(chars)

# Tokenization (character-level)
stoi = { ch:i for i,ch in enumerate(chars) }
itos = { i:ch for i,ch in enumerate(chars) }
encode = lambda s: [stoi[c] for c in s] # encoder: take a string, output a list of integers
decode = lambda l: ''.join([itos[i] for i in l]) # decoder: take a list of integers, output a string

data = torch.tensor(encode(text), dtype=torch.long)

n = int(0.9*len(data)) # 90-10 train-test split
train_data = data[:n]
val_data = data[n:]

# data loading
def get_batch(split):
    data = train_data if split=='train' else val_data
    ix = torch.randint(len(data)-block_size, (batch_size,))
    x = torch.stack([data[i:i+block_size] for i in ix])
    y = torch.stack([data[i+1:i+block_size+1] for i in ix])
    x, y = x.to(device), y.to(device)
    return x, y

# estimate loss (no_grad == don't call backward while doing)
@torch.no_grad()
def estimate_loss():
    out = {}
    model.eval()
    for split in ['train', 'val']:
        losses = torch.zeros(eval_iters)
        for k in range(eval_iters):
            X, Y = get_batch(split)
            logits, loss = model(X, Y)
            losses[k] = loss.item()
        out[split] = losses.mean()
    model.train()
    return out

# Head module
class Head(nn.Module):
    """ one head of self-attention """
    def __init__(self, head_size):
        super().__init__()
        self.key = nn.Linear(n_embd, head_size, bias=False)
        self.query = nn.Linear(n_embd, head_size, bias=False)
        self.value = nn.Linear(n_embd, head_size, bias=False)
        self.register_buffer('tril', torch.tril(torch.ones(block_size, block_size)))
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        B,T,C = x.shape
        k = self.key(x)     # (B,T,C)
        q = self.query(x)   # (B,T,C)
        # compute attention scores ("affinities")
        wei = q @ k.transpose(-2, -1) * C**-0.5 # (B,T,C) @ (B,C,T) ---> (B,T,T)
        wei = wei.masked_fill(self.tril[:T, :T] == 0, float('-inf')) # (B,T,T)
        wei = F.softmax(wei, dim=-1) # (B,T,T)
        wei = self.dropout(wei)
        # Perform the weighted aggregation of the values
        v = self.value(x) # (B,T,C)
        out = wei @ v # (B,T,T) @ (B,T,C) ---> (B,T,C)
        return out


class MultiHeadAttention(nn.Module):
    """ multiple heads of self-attention in parallel """
    def __init__(self, num_heads, head_size):
        super().__init__()
        self.heads = nn.ModuleList([Head(head_size) for _ in range(num_heads)])
        self.proj = nn.Linear(n_embd, n_embd)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        out = torch.cat([h(x) for h in self.heads], dim=-1)
        out = self.dropout(self.proj(out))
        return out


class FeedForward(nn.Module):
    """ a simple linear layer followed by a non-linearity """
    def __init__(self, n_embd):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_embd, 4 * n_embd),
            nn.ReLU(),
            nn.Linear(4 * n_embd, n_embd),
            nn.Dropout(dropout),
        )
    
    def forward(self, x):
        return self.net(x)


class Block(nn.Module):
    """ Transformer Residual block: communication followed by computation """
    def __init__(self, n_embd, n_head):
        super().__init__()
        head_size = n_embd // n_head
        self.sa = MultiHeadAttention(n_head, head_size)  # apply one head of self-attention. (B,T,C)
        self.ffwd = FeedForward(n_embd) # Just give'em some time to learn by passing through an innoffensive layer
        self.ln1 = nn.LayerNorm(n_embd)
        self.ln2 = nn.LayerNorm(n_embd)

    def forward(self, x):
        # sum x for residual connection
        x = x + self.sa(self.ln1(x))
        x = x + self.ffwd(self.ln2(x))
        return x


# Bigram model
class BigramLanguageModel(nn.Module):
    """ When referring to B,T,C:
        B: number of batches
        T: "time component" Basically the required "context" to make a prediction
        C: number of channels. In our case, n_embd
    """
    def __init__(self):
        super().__init__()
        # each token directly reads off the logits for the next token from a lookup table
        self.token_embedding_table = nn.Embedding(vocab_size, n_embd)
        self.position_embedding_table = nn.Embedding(block_size, n_embd)
        self.blocks = nn.Sequential(*[Block(n_embd, n_head=n_heads) for _ in range(n_layer)])
        self.ln_f = nn.LayerNorm(n_embd) # final layer norm
        self.lm_head = nn.Linear(n_embd, vocab_size)
        
    def forward(self, idx, targets=None):
        B,T = idx.shape

        # idx and targets are both (B, T) tensor of integers
        tok_embedding = self.token_embedding_table(idx) # (B,T,C)
        pos_embedding = self.position_embedding_table(torch.arange(T, device=device)) # (T,C)
        x = tok_embedding + pos_embedding # (B,T,C)
        x = self.blocks(x) # (B,T,C)
        x = self.ln_f(x) # (B,T,C)
        logits = self.lm_head(x) # (B,T,vocab_size)

        if targets is None:
            loss = None
        else:
            B,T,C = logits.shape
            logits = logits.view(B*T, C) # reshape (B,T,C) to (B*T,C)
            targets = targets.view(B*T)  # reshape (B,T) to (B*T,)
            loss = F.cross_entropy(logits, targets)
        
        return logits, loss
    
    def generate(self, idx, max_new_tokens):
        # idx is (B,T) array of indices in the current context
        for _ in range(max_new_tokens):
            # crop idx to the last block_size tokens
            idx_cond = idx[:, -block_size:]
            # get the predictions
            logits, loss = self(idx_cond)
            # focus only on the last time step
            logits = logits[:, -1, :]
            # apply softmax to get probabilities
            probs = F.softmax(logits, dim=1)
            # sample from the distribution
            idx_next = torch.multinomial(probs, num_samples=1)
            # append sampled index to the running sequence
            idx = torch.cat((idx, idx_next), dim=1)
        return idx


def generate_some_text(num_chars):
    model = BigramLanguageModel()
    model.load_state_dict(torch.load(SAVE_PATH))
    model.to(device)
    context = torch.zeros((1,1), dtype=torch.long, device=device)
    return decode(model.generate(context, max_new_tokens=num_chars)[0].tolist())

##################################################################################################
##################################################################################################
##################################################################################################

if not args['generate']:
    model = BigramLanguageModel()
    model.to(device)

    # Train the Bigram model
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)

    print('Beginning training')
    for iter in range(max_iters):
        if iter % eval_interval == 0:
            losses = estimate_loss()
            torch.save(model.state_dict(), SAVE_PATH)
            print(f"step {iter}: train loss {losses['train']:.4f}, val loss {losses['val']:.4f}")
        
        # sample a batch of data
        xb, yb = get_batch('train')
        
        # evaluate the loss
        logits, loss = model(xb, yb)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()

    torch.save(model.state_dict(), SAVE_PATH)

    # Generating stuff
    print(generate_some_text(400))

else:
    text = generate_some_text(int(args['generate']))

    with open('output.txt', 'w') as f:
        f.write(text)
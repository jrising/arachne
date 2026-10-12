cost.input <- 0.5 / 1e6
cost.output <- 1.5 / 1e6

doc.tokens <- 2000
query.tokens <- 200
extract.tokens <- 500
response.tokens <- 500
brief.tokens <- 200

## doc.to.extract <- function(num.query) {
##     (doc.tokens + num.query * query.tokens) + num.query * extract.tokens
## }

## respond.query.with.extract <- function(num.doc) {
##     (num.doc * extract.tokens) + response.tokens
## }

## doc.to.extract <- function() {
##     doc.tokens + extract.tokens
## }

## query.to.brief <- function() {
##     query.tokens + brief.tokens
## }

## extracts.to.extract <- function(num.doc) {
##     num.doc * extract.tokens + extract.tokens
## }

calc.info.per.cent <- function(num.doc, num.query) {
    df <- data.frame()
    for (summarize.doc in c(F, T)) {
        if (summarize.doc) {
            cost.sumdoc <- num.doc * (cost.input * doc.tokens + cost.output * extract.tokens)
            my.doc.tokens <- extract.tokens
            doc.note <- ", summarized docs"
        } else {
            cost.sumdoc <- 0
            my.doc.tokens <- doc.tokens
            doc.note <- ""
        }

        for (summarize.query in c(F, T)) {
            if (summarize.query) {
                cost.sumquery <- num.query * (cost.input * query.tokens + cost.output * brief.tokens)
                my.query.tokens <- brief.tokens
                query.note <- ", summarized query"
            } else {
                cost.sumquery <- 0
                my.query.tokens <- query.tokens
                query.note <- ""
            }

            ## Option 1: Pass in all documents for each query
            input.tokens <- num.doc * my.doc.tokens + my.query.tokens
            info <- num.query * num.doc * log(my.doc.tokens)
            cost <- num.query * (cost.input * input.tokens + cost.output * response.tokens)

            df <- rbind(df, data.frame(method=paste0("All documents", doc.note, query.note), info, cost=cost + cost.sumdoc + cost.sumquery))

            ## Option 2: First extract from each document
            input.tokens.step1 <- my.doc.tokens + my.query.tokens
            info.step1 <- log(extract.tokens)
            cost.step1 <- cost.input * input.tokens.step1 + cost.output * extract.tokens

            for (summarize.extracts in c(F, T)) {
                if (summarize.extracts) {
                    cost.sumextracts <- cost.input * num.doc * extract.tokens + cost.output * extract.tokens
                    my.extracts.tokens <- extract.tokens
                    info.step2 <- log(extract.tokens)
                    extracts.note <- ", summarized extracts"
                } else {
                    cost.sumextracts <- 0
                    my.extracts.tokens <- num.doc * extract.tokens
                    info.step2 <- num.doc * info.step1
                    extracts.note <- ""
                }

                input.tokens.step2 <- my.extracts.tokens + my.query.tokens
                cost.step2 <- cost.input * input.tokens.step2 + cost.output * response.tokens

                df <- rbind(df, data.frame(method=paste0("Extracts first", doc.note, query.note, extracts.note), info=info.step2, cost=cost.step1 + cost.step2 + cost.sumdoc + cost.sumquery + cost.sumextracts))
            }
        }
    }
    df
}

df <- calc.info.per.cent(100, 10)
df$metric <- df$info / df$cost
## Extracts first is the winner

df <- calc.info.per.cent(100, 1)
df$metric <- df$info / df$cost
## Extracts first is the winner

df <- calc.info.per.cent(10, 1)
df$metric <- df$info / df$cost
## Extracts first is the winner

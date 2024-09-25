import pyspark.sql.functions as F
from pandas import DataFrame
from pyspark.sql import Window
from pyspark.sql.types import MapType, StringType, DateType

class FeatureEngineer:
    def __init__(self, spark_manager):
        self.spark = spark_manager.spark
        self.dataframe = spark_manager.dataframe

    def print_shape(self, message: str,df):
        print(f"{message} - Shape: {df.count()} rows, {len(df.columns)} columns")

    def add_comorbidities_array(self):
        df = self.dataframe
        self.print_shape("Initial DataFrame", df)

        window_spec = Window.partitionBy('patient_id').orderBy('claim_statement_from_date') \
            .rowsBetween(Window.unboundedPreceding, -1)

        df = df.withColumn(
            'previous_comorbidities',
            F.array_distinct(F.flatten(F.collect_list('claim_all_diagnosis_codes').over(window_spec)))
        )

        self.print_shape("DataFrame After Window Function", df)

        self.dataframe = df

    def add_procedure_array(self, procedure_column, date_column):
        df = self.dataframe
        self.print_shape(f"Initial DataFrame for {procedure_column}", df)
    
        # Define a window specification that partitions by patient_id and orders by claim_statement_from_date
        window_spec = Window.partitionBy('patient_id').orderBy('claim_statement_from_date') \
            .rowsBetween(Window.unboundedPreceding, -1)
    
        # Filter out rows where either the procedure or date is null
        df = df.withColumn(
            'filtered_procedure',
            F.when(F.col(procedure_column).isNotNull() & F.col(date_column).isNotNull(), F.col(procedure_column))
        ).withColumn(
            'filtered_date',
            F.when(F.col(procedure_column).isNotNull() & F.col(date_column).isNotNull(), F.col(date_column))
        )
    
        # Create a map (procedure, date) pair
        df = df.withColumn(
            f'procedure_date_map',
            F.map_from_arrays(
                F.collect_list('filtered_procedure').over(window_spec), 
                F.collect_list('filtered_date').over(window_spec)
            )
        )
    
        # Define a UDF to keep the procedure with the latest date
        def update_procedure_map(procedure_date_map):
            if not procedure_date_map:
                return {}
            latest_map = {}
            for procedure, date in procedure_date_map.items():
                if procedure not in latest_map or date > latest_map[procedure]:
                    latest_map[procedure] = date
            return latest_map
    
        # Register the UDF with PySpark
        update_procedure_map_udf = F.udf(update_procedure_map, MapType(StringType(), StringType()))
    
        # Apply the UDF to update the procedure map with the latest date for each procedure
        df = df.withColumn(
            f'updated_procedure_date_map',
            update_procedure_map_udf(F.col(f'procedure_date_map'))
        )
    
        self.print_shape(f"DataFrame After Window Function for {procedure_column}", df)
    
        # Set the dataframe back to the instance
        self.dataframe = df

    def display_head(self, n=5):
        pandas_df = self.dataframe.limit(n).toPandas()
        return pandas_df

    def get_rows_by_column_value(self, column_name: str, value) -> DataFrame:
        return self.dataframe.filter(self.dataframe[column_name] == value).toPandas()

    def remove_diagnosis_codes(self, diagnosis_list):
        df = self.dataframe

        df_exploded = df.withColumn("exploded_diagnosis", F.explode(F.col("claim_all_diagnosis_codes")))

        df_filtered = df_exploded.filter(~F.col("exploded_diagnosis.diagnosis_code").isin(diagnosis_list))

        df_filtered = df_filtered.groupBy([col for col in df.columns if col != "claim_all_diagnosis_codes"]).agg(
            F.collect_list("exploded_diagnosis").alias("claim_all_diagnosis_codes")
        )

        self.print_shape("DataFrame After Removing Diagnosis Codes", df_filtered)
        self.dataframe = df_filtered

    def calculate_first_visit_and_duration(self):
        df = self.dataframe
        window_spec = Window.partitionBy('patient_id').orderBy('claim_statement_from_date')
        df = df.withColumn('first_visit_date', F.first('claim_statement_from_date').over(window_spec))
        df = df.withColumn('days_since_first_visit',
                           F.datediff(F.col('claim_statement_from_date'), F.col('first_visit_date')))

        self.print_shape("DataFrame After Calculating First Visit Date and Duration", df)
        self.dataframe = df

    def get_min_max(self, column_name: str):
        df = self.dataframe

        min_value = df.agg(F.min(column_name)).collect()[0][0]
        max_value = df.agg(F.max(column_name)).collect()[0][0]

        print(f"Min: {min_value}, Max: {max_value}")


    def add_train_test_indicator(self, test_size: float = 0.2) -> DataFrame:

        unique_patient_ids = self.dataframe.select('patient_id').distinct()
        test_patient_ids = unique_patient_ids.sample(False, test_size, seed=42).collect()

        test_patient_id_list = [row['patient_id'] for row in test_patient_ids]

        self.dataframe = self.dataframe.withColumn(
            'train_test',
            F.when(F.col('patient_id').isin(test_patient_id_list), 'test').otherwise('train')
        )

        return self.display_head()
